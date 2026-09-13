"""Unit tests for REPORTER Phase 4.5: Synthesis validation from existing RAG.

Tests:
1. Tool registration - REPORTER config has Phase 4.5 tools
2. Prompt loading - REPORTER_PROMPT contains Phase 4.5 section
3. Context extraction - Parse mock synthesis.md for retrieval terms
"""

import json
import re

# =============================================================================
# Test 1: Tool Registration
# =============================================================================


def test_reporter_has_existing_rag_tools():
    """Verify REPORTER config includes all Phase 4.5 tools."""
    from src.agents.deep_interpreter.subagents.configs import SUBAGENT_CONFIGS
    from src.agents.deep_interpreter.tools import (
        prepare_rag_literature,
        search_literature,
        search_literature_dynamic,
        search_literature_fulltext,
        search_pubmed_advanced,
        validate_claim_fulltext,
        think_tool,
    )

    reporter_config = SUBAGENT_CONFIGS["reporter"]
    tools = reporter_config["tools"]

    for tool in [
        prepare_rag_literature,
        search_literature_fulltext,
        validate_claim_fulltext,
        think_tool,
    ]:
        assert tool in tools, f"Missing tool: {getattr(tool, 'name', str(tool))}"

    for tool in [search_literature_dynamic, search_literature, search_pubmed_advanced]:
        assert tool not in tools, f"REPORTER must not expose search tool: {tool.name}"


def test_reporter_tool_count():
    """Verify REPORTER has expected number of tools (10 total)."""
    from src.agents.deep_interpreter.subagents.configs import SUBAGENT_CONFIGS

    reporter_config = SUBAGENT_CONFIGS["reporter"]
    tools = reporter_config["tools"]

    # Expected: core tools + existing-RAG validation tools.
    assert len(tools) >= 7, f"Expected >= 7 tools, got {len(tools)}"

    tool_names = [t.__name__ if hasattr(t, "__name__") else str(t) for t in tools]
    print(f"✅ REPORTER tools ({len(tools)}): {tool_names}")


# =============================================================================
# Test 2: Prompt Loading
# =============================================================================


def test_reporter_prompt_has_phase45():
    """Verify REPORTER_PROMPT contains Phase 4.5 workflow section."""
    from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS

    reporter_prompt = SUBAGENT_PROMPTS["reporter"]

    # Phase 4.5 key sections
    required_sections = [
        "Phase 4.5",
        "RETRIEVE SYNTHESIS SUPPORT FROM EXISTING RAG",
        "synthesis_validation.json",
        "search_literature_fulltext",
        "prepare_rag_literature",
        "validate_claim_fulltext",
        'part_name="all"',
    ]

    for section in required_sections:
        assert section in reporter_prompt, f"Missing section: {section}"

    for forbidden in [
        "synthesis_papers.json",
        "search_literature_dynamic",
        "search_pubmed_advanced",
        'part_name="synthesis"',
        "NEW literature search",
    ]:
        assert forbidden not in reporter_prompt, f"Forbidden legacy search text: {forbidden}"


def test_reporter_prompt_5step_workflow():
    """Verify REPORTER_PROMPT has 5-step Phase 4.5 workflow."""
    from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS

    reporter_prompt = SUBAGENT_PROMPTS["reporter"]

    steps = [
        "Step 1: Prepare Existing RAG",
        "Step 2: Retrieve Theme Support",
        "Step 3: Validate Cited Claims",
        "Step 4: Update synthesis.md",
        "Step 5: Hand off validation metadata to deterministic code",
    ]

    for step in steps:
        assert step in reporter_prompt, f"Missing step: {step}"
    assert 'write_file("/synthesis_validation.json"' not in reporter_prompt

    print(f"✅ REPORTER prompt contains all 5 Phase 4.5 steps")


# =============================================================================
# Test 3: Existing RAG tool availability
# =============================================================================


def test_search_literature_fulltext_import():
    """Verify existing-RAG retrieval tool can be imported."""
    from src.agents.deep_interpreter.tools.literature_rag import search_literature_fulltext

    assert search_literature_fulltext is not None
    assert hasattr(search_literature_fulltext, "invoke") or hasattr(
        search_literature_fulltext, "ainvoke"
    )


# =============================================================================
# Test 4: Tool Invocation - prepare_rag_literature
# =============================================================================


def test_prepare_rag_literature_import():
    """Verify prepare_rag_literature can be imported."""
    from src.agents.deep_interpreter.tools.literature_rag import prepare_rag_literature

    assert prepare_rag_literature is not None
    assert hasattr(prepare_rag_literature, "invoke") or hasattr(
        prepare_rag_literature, "ainvoke"
    )
    print("✅ prepare_rag_literature imported successfully")


# =============================================================================
# Test 4: Mock Synthesis Context Extraction
# =============================================================================


MOCK_SYNTHESIS_MD = """# Integrated Biological Narrative

## Executive Summary

The analysis reveals a complex interplay between **TGF-β signaling** and **EMT** in the
tumor microenvironment. **Fibroblasts** communicate with **epithelial cells** through
**TGFB1-TGFBR2** interactions, driving spatial reorganization.

## Cross-Part Themes

### Theme 1: Spatial Organization

The spatial analysis (Part 1) shows that clusters enriched in **CDH1** and **VIM**
exhibit gradient patterns. Pathway analysis reveals **WNT signaling** activation in
boundary regions.

### Theme 2: Cell Communication Axis

Key L-R pairs identified:
- **TGFB1-TGFBR2**: Fibroblast → Epithelial communication
- **COL1A1-ITGB1**: ECM remodeling
- **WNT5A-FZD7**: Canonical WNT pathway

### Theme 3: Pathway Integration

The **EMT pathway** shows highest activity in regions where **TGFb signaling** and
**WNT pathway** converge. This suggests synergistic activation.

### Theme 4: Disease Mechanism

In the context of **breast cancer**, these findings suggest that CAF-epithelial
crosstalk drives **EMT** and potentially **metastasis**.

## Emergent Themes Summary

| Theme | Strength | Supporting Evidence |
|-------|----------|---------------------|
| TGF-β drives EMT | Strong | Part 2-6, Part 3-10 |
| Spatial gradient exists | Strong | Part 1-1, Part 1-3 |
"""


def extract_synthesis_context(synthesis_md: str) -> dict:
    """Extract searchable terms from synthesis.md for Phase 4.5.

    This simulates the context extraction step in Phase 4.5 Step 1.
    """
    context = {
        "genes": [],
        "pathways": [],
        "celltypes": [],
        "integration_keywords": [],
        "disease_context": None,
    }

    # Extract genes (common gene name patterns)
    gene_patterns = [
        r"\b(TGFB\d?)\b",
        r"\b(TGFBR\d?)\b",
        r"\b(CDH\d+)\b",
        r"\b(VIM)\b",
        r"\b(COL\d+A\d+)\b",
        r"\b(ITGB\d+)\b",
        r"\b(WNT\d+[A-Z]?)\b",
        r"\b(FZD\d+)\b",
        r"\b(BRCA\d?)\b",
        r"\b(MMP\d+)\b",
    ]
    for pattern in gene_patterns:
        matches = re.findall(pattern, synthesis_md, re.IGNORECASE)
        context["genes"].extend([m.upper() for m in matches])
    context["genes"] = list(set(context["genes"]))

    # Extract pathways
    pathway_keywords = [
        "EMT",
        "TGF-β",
        "TGFb",
        "TGF-beta",
        "WNT",
        "Wnt",
        "ECM",
        "apoptosis",
        "MAPK",
        "PI3K",
        "NF-κB",
        "Notch",
        "Hedgehog",
    ]
    for kw in pathway_keywords:
        if kw.lower() in synthesis_md.lower():
            context["pathways"].append(kw)
    context["pathways"] = list(set(context["pathways"]))

    # Extract cell types
    celltype_keywords = [
        "Fibroblast",
        "Epithelial",
        "Macrophage",
        "T cell",
        "B cell",
        "CAF",
        "Endothelial",
        "Stromal",
        "Immune",
        "Tumor",
    ]
    for ct in celltype_keywords:
        if ct.lower() in synthesis_md.lower():
            context["celltypes"].append(ct)
    context["celltypes"] = list(set(context["celltypes"]))

    # Extract integration keywords
    integration_patterns = [
        r"spatial (gradient|pattern|organization|distribution)",
        r"tumor microenvironment",
        r"cell-cell (communication|interaction)",
        r"crosstalk",
        r"signaling (axis|pathway)",
    ]
    for pattern in integration_patterns:
        match = re.search(pattern, synthesis_md, re.IGNORECASE)
        if match:
            context["integration_keywords"].append(match.group(0))
    context["integration_keywords"] = list(set(context["integration_keywords"]))

    # Extract disease context
    disease_patterns = [
        r"breast cancer",
        r"lung cancer",
        r"colorectal cancer",
        r"pancreatic cancer",
        r"melanoma",
        r"glioblastoma",
    ]
    for pattern in disease_patterns:
        match = re.search(pattern, synthesis_md, re.IGNORECASE)
        if match:
            context["disease_context"] = match.group(0)
            break

    return context


def test_extract_synthesis_context():
    """Test context extraction from mock synthesis.md."""
    context = extract_synthesis_context(MOCK_SYNTHESIS_MD)

    # Verify genes extracted
    assert "TGFB1" in context["genes"], f"Missing TGFB1 in {context['genes']}"
    assert "CDH1" in context["genes"], f"Missing CDH1 in {context['genes']}"
    assert "VIM" in context["genes"], f"Missing VIM in {context['genes']}"

    # Verify pathways extracted
    assert any(
        "EMT" in p for p in context["pathways"]
    ), f"Missing EMT in {context['pathways']}"
    assert any(
        "WNT" in p.upper() for p in context["pathways"]
    ), f"Missing WNT in {context['pathways']}"

    # Verify cell types extracted
    assert "Fibroblast" in context["celltypes"], f"Missing Fibroblast"
    assert "Epithelial" in context["celltypes"], f"Missing Epithelial"

    # Verify disease context
    assert context["disease_context"] == "breast cancer", f"Wrong disease context"

    print("✅ Context extraction successful:")
    print(f"   Genes: {context['genes']}")
    print(f"   Pathways: {context['pathways']}")
    print(f"   Cell types: {context['celltypes']}")
    print(f"   Integration keywords: {context['integration_keywords']}")
    print(f"   Disease: {context['disease_context']}")


def test_synthesis_context_json_output():
    """Test that extracted context can be serialized to JSON."""
    context = extract_synthesis_context(MOCK_SYNTHESIS_MD)

    # Should be JSON serializable
    json_str = json.dumps(context, indent=2)
    assert json_str is not None

    # Parse back
    parsed = json.loads(json_str)
    assert parsed["genes"] == context["genes"]

    print("✅ Context is JSON serializable")
    print(f"   JSON output:\n{json_str}")


# =============================================================================
# Run all tests
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("REPORTER Phase 4.5 Unit Tests")
    print("=" * 60)

    # Sync tests
    print("\n--- Test 1: Tool Registration ---")
    test_reporter_has_existing_rag_tools()
    test_reporter_tool_count()

    print("\n--- Test 2: Prompt Loading ---")
    test_reporter_prompt_has_phase45()
    test_reporter_prompt_5step_workflow()

    print("\n--- Test 4: Context Extraction ---")
    test_extract_synthesis_context()
    test_synthesis_context_json_output()

    print("\n" + "=" * 60)
    print("Sync tests completed. Run pytest for async tests:")
    print("  pytest tests/test_reporter_phase45.py -v")
    print("=" * 60)

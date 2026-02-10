"""Unit tests for PLANNER subagent workflow.

Tests:
1. Tool registration - PLANNER config has exactly 4 tools
2. Prompt content - PLANNER_PROMPT contains 6-step workflow
3. generate_biomedical_context tool signature and mock invocation
4. search_pubmed_advanced tool signature and mock invocation
5. Output file expectations in prompt
6. Graph builder creates PLANNER subagent graph
"""

import pytest


# =============================================================================
# Test 1: Tool Registration
# =============================================================================


def test_planner_has_correct_tools():
    """Verify PLANNER config includes exactly the 4 expected tools."""
    from src.agents.deep_interpreter.subagents.configs import SUBAGENT_CONFIGS
    from src.agents.deep_interpreter.tools import (
        load_analysis_data,
        generate_biomedical_context,
        search_pubmed_advanced,
        think_tool,
    )

    planner_config = SUBAGENT_CONFIGS["planner"]
    tools = planner_config["tools"]

    required_tools = [
        load_analysis_data,
        generate_biomedical_context,
        search_pubmed_advanced,
        think_tool,
    ]

    for tool in required_tools:
        assert tool in tools, f"Missing tool: {tool.__name__}"

    print(f"PLANNER has all {len(required_tools)} required tools")


def test_planner_tool_count():
    """Verify PLANNER has exactly 4 tools."""
    from src.agents.deep_interpreter.subagents.configs import SUBAGENT_CONFIGS

    planner_config = SUBAGENT_CONFIGS["planner"]
    tools = planner_config["tools"]

    assert len(tools) == 4, f"Expected 4 tools, got {len(tools)}"

    tool_names = [t.__name__ if hasattr(t, "__name__") else str(t) for t in tools]
    print(f"PLANNER tools ({len(tools)}): {tool_names}")


# =============================================================================
# Test 2: Prompt Content - 6-Step Workflow
# =============================================================================


def test_planner_prompt_has_6_steps():
    """Verify PLANNER_PROMPT contains all 6 steps."""
    from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS

    planner_prompt = SUBAGENT_PROMPTS["planner"]

    steps = [
        "Step 1: Read Target Configuration",
        "Step 2: Load Analysis Data",
        "Step 3: Generate Biomedical Context",
        "Step 4: Literature Initialization",
        "Step 5: Analysis Coverage Checklist",
        "Step 6: Write Interpretation Guide",
    ]

    for step in steps:
        assert step in planner_prompt, f"Missing step: {step}"

    print(f"PLANNER prompt contains all 6 workflow steps")


def test_planner_prompt_references_tools():
    """Verify PLANNER_PROMPT references all 4 tools."""
    from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS

    planner_prompt = SUBAGENT_PROMPTS["planner"]

    tool_references = [
        "load_analysis_data",
        "generate_biomedical_context",
        "search_pubmed_advanced",
        "think_tool",
    ]

    for ref in tool_references:
        assert ref in planner_prompt, f"Missing tool reference: {ref}"

    print("PLANNER prompt references all 4 tools")


def test_planner_prompt_output_files():
    """Verify PLANNER_PROMPT specifies correct output files."""
    from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS

    planner_prompt = SUBAGENT_PROMPTS["planner"]

    output_files = [
        "/interpretation_guide.md",
        "/analysis_summary.md",
        "/data_path.txt",
        "/planner_literature_context.md",
        "/planner_biomcp_context.md",
    ]

    for f in output_files:
        assert f in planner_prompt, f"Missing output file reference: {f}"

    print(f"PLANNER prompt references all {len(output_files)} output files")


def test_planner_prompt_no_strategic_plan():
    """Verify PLANNER_PROMPT does NOT reference old /strategic_plan.md."""
    from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS

    planner_prompt = SUBAGENT_PROMPTS["planner"]

    assert "/strategic_plan.md" not in planner_prompt, (
        "PLANNER prompt still references old /strategic_plan.md"
    )

    print("PLANNER prompt correctly uses /interpretation_guide.md (not /strategic_plan.md)")


# =============================================================================
# Test 3: generate_biomedical_context Tool Signature
# =============================================================================


def test_generate_biomedical_context_signature():
    """Verify generate_biomedical_context tool accepts expected parameters."""
    from src.agents.deep_interpreter.tools.literature import generate_biomedical_context

    assert hasattr(generate_biomedical_context, "invoke") or hasattr(
        generate_biomedical_context, "ainvoke"
    )

    # Check the tool's input schema matches expected parameters
    schema = generate_biomedical_context.args_schema.model_json_schema()
    properties = schema.get("properties", {})

    expected_params = ["celltypes", "pathways", "available_analyses", "disease"]
    for param in expected_params:
        assert param in properties, (
            f"Missing parameter '{param}' in generate_biomedical_context schema. "
            f"Found: {list(properties.keys())}"
        )

    print(f"generate_biomedical_context has correct parameters: {expected_params}")


def test_generate_biomedical_context_returns_dict():
    """Verify generate_biomedical_context returns expected structure on failure."""
    from src.agents.deep_interpreter.tools.literature import generate_biomedical_context

    # Call with minimal input - should return gracefully even without BioMCP
    result = generate_biomedical_context.invoke({
        "celltypes": ["Fibroblast", "Epithelial"],
        "pathways": ["EMT", "TGFb"],
        "available_analyses": "Part 1: spatial, Part 2: CCI",
        "disease": "breast cancer",
    })

    assert result is not None
    # Result should be a dict (or string representation) with success field
    if isinstance(result, dict):
        assert "success" in result, f"Missing 'success' key in result: {result.keys()}"
        print(f"generate_biomedical_context returned dict with success={result['success']}")
    else:
        # Tool may return string - just verify it's not empty
        assert len(str(result)) > 0
        print(f"generate_biomedical_context returned: {str(result)[:100]}...")


# =============================================================================
# Test 4: search_pubmed_advanced Tool Signature
# =============================================================================


def test_search_pubmed_advanced_signature():
    """Verify search_pubmed_advanced accepts expected parameters."""
    from src.agents.deep_interpreter.tools.pubmed_eutils import search_pubmed_advanced

    assert hasattr(search_pubmed_advanced, "invoke") or hasattr(
        search_pubmed_advanced, "ainvoke"
    )

    schema = search_pubmed_advanced.args_schema.model_json_schema()
    properties = schema.get("properties", {})

    # Must have query parameter
    assert "query" in properties, (
        f"Missing 'query' parameter. Found: {list(properties.keys())}"
    )

    # Should have max_results and sort
    assert "max_results" in properties, "Missing 'max_results' parameter"
    assert "sort" in properties, "Missing 'sort' parameter"

    print(f"search_pubmed_advanced has correct parameters: {list(properties.keys())}")


# =============================================================================
# Test 5: PLANNER Config Description
# =============================================================================


def test_planner_config_description():
    """Verify PLANNER config description mentions key outputs."""
    from src.agents.deep_interpreter.subagents.configs import SUBAGENT_CONFIGS

    planner_config = SUBAGENT_CONFIGS["planner"]
    description = planner_config["description"]

    assert "interpretation_guide.md" in description, "Missing interpretation_guide.md in description"
    assert "biomedical context" in description.lower(), "Missing biomedical context in description"

    print(f"PLANNER description mentions key outputs")


# =============================================================================
# Test 6: Graph Builder Creates PLANNER Subagent
# =============================================================================


def test_planner_subagent_graph_creation():
    """Verify planner_subagent_graph is created successfully."""
    from src.agents.deep_interpreter.graph_builder import planner_subagent_graph

    assert planner_subagent_graph is not None
    print("planner_subagent_graph created successfully")


def test_planner_subagent_via_factory():
    """Verify create_subagent_graph('planner') works."""
    from src.agents.deep_interpreter.graph_builder import create_subagent_graph

    graph = create_subagent_graph("planner", provider="openai")
    assert graph is not None
    print("create_subagent_graph('planner') works correctly")


# =============================================================================
# Test 7: Workflow Chain - PLANNER outputs consumed by downstream
# =============================================================================


def test_planner_outputs_referenced_by_searcher():
    """Verify SEARCHER prompt references PLANNER output files."""
    from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS

    searcher_prompt = SUBAGENT_PROMPTS["searcher"]

    # SEARCHER should reference PLANNER's output files
    assert "/data_path.txt" in searcher_prompt, "SEARCHER missing /data_path.txt reference"

    print("SEARCHER correctly references PLANNER output files")


def test_planner_outputs_referenced_by_interpreter():
    """Verify INTERPRETER prompt references PLANNER output files."""
    from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS

    interpreter_prompt = SUBAGENT_PROMPTS["interpreter"]

    assert "/interpretation_guide.md" in interpreter_prompt, (
        "INTERPRETER missing /interpretation_guide.md reference"
    )
    assert "/data_path.txt" in interpreter_prompt, (
        "INTERPRETER missing /data_path.txt reference"
    )

    print("INTERPRETER correctly references PLANNER output files")


def test_planner_outputs_referenced_by_reporter():
    """Verify REPORTER prompt references PLANNER output files."""
    from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS

    reporter_prompt = SUBAGENT_PROMPTS["reporter"]

    assert "/interpretation_guide.md" in reporter_prompt, (
        "REPORTER missing /interpretation_guide.md reference"
    )

    print("REPORTER correctly references PLANNER output files")


# =============================================================================
# Run all tests
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("PLANNER Workflow Unit Tests")
    print("=" * 60)

    print("\n--- Test 1: Tool Registration ---")
    test_planner_has_correct_tools()
    test_planner_tool_count()

    print("\n--- Test 2: Prompt Content ---")
    test_planner_prompt_has_6_steps()
    test_planner_prompt_references_tools()
    test_planner_prompt_output_files()
    test_planner_prompt_no_strategic_plan()

    print("\n--- Test 3: generate_biomedical_context ---")
    test_generate_biomedical_context_signature()
    test_generate_biomedical_context_returns_dict()

    print("\n--- Test 4: search_pubmed_advanced ---")
    test_search_pubmed_advanced_signature()

    print("\n--- Test 5: Config Description ---")
    test_planner_config_description()

    print("\n--- Test 6: Graph Builder ---")
    test_planner_subagent_graph_creation()
    test_planner_subagent_via_factory()

    print("\n--- Test 7: Workflow Chain ---")
    test_planner_outputs_referenced_by_searcher()
    test_planner_outputs_referenced_by_interpreter()
    test_planner_outputs_referenced_by_reporter()

    print("\n" + "=" * 60)
    print("All sync tests completed. Run pytest for full suite:")
    print("  pytest tests/test_planner_workflow.py -v")
    print("=" * 60)

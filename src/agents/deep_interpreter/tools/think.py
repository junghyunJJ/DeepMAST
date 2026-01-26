"""Think tool for Deep Interpreter Agent.

This tool provides quality validation using the reflection-tool MCP server
with iteration tracking for the quality validation loop.
"""

import asyncio
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


async def _invoke_think_tool(reflection_text: str) -> dict:
    """Invoke the reflection-tool MCP server's think_tool.

    Args:
        reflection_text: The reflection prompt to process

    Returns:
        Dictionary with thinking result and metadata
    """
    try:
        async with MultiServerMCPClient(
            {"reflection": REFLECTION_TOOL_CONFIG}
        ) as client:
            tools = client.get_tools()

            # Find think_tool
            think_tool_obj = None
            for tool_obj in tools:
                if hasattr(tool_obj, 'name') and 'think' in tool_obj.name:
                    think_tool_obj = tool_obj
                    break

            if think_tool_obj is None:
                return {
                    "success": False,
                    "error": "think_tool not found in reflection MCP server",
                    "result": None,
                }

            # Invoke think_tool
            result = await think_tool_obj.ainvoke({"reflection": reflection_text})

            return {
                "success": True,
                "result": str(result),
                "tool_name": think_tool_obj.name,
            }

    except Exception as e:
        return {
            "success": False,
            "error": f"Reflection-tool invocation failed: {e}",
            "result": None,
        }


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

    # Run async function
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    _invoke_think_tool(enhanced_reflection)
                )
                result = future.result(timeout=60)
        else:
            result = asyncio.run(_invoke_think_tool(enhanced_reflection))

        # Parse score from result if available
        parsed_score = None
        if result.get("success") and result.get("result"):
            result_text = result["result"].lower()
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

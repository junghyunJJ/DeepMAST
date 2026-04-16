"""Contract tests for think_tool — pins the shared tool defaults.

Trip-wire: if these tests fail, think_tool defaults drifted. DrugTarget
relies on score_threshold=0.7 default at 6 call sites (prompts.py:27,245,
318,530,554,640). INTERPRETER passes score_threshold=0.8 as an explicit
call-site kwarg — never by editing the tool default.
"""

from __future__ import annotations

import inspect

from src.agents.deep_interpreter.tools.think import think_tool


def test_think_tool_score_threshold_default_is_0_7():
    """INTERPRETER overrides this to 0.8 via call-site kwarg, not tool default."""
    sig = inspect.signature(think_tool.func)
    default = sig.parameters["score_threshold"].default
    assert default == 0.7, (
        f"think_tool.score_threshold default must remain 0.7 (DrugTarget relies on this). "
        f"Got {default}. INTERPRETER passes 0.8 as an explicit kwarg."
    )


def test_think_tool_max_iterations_default_is_3():
    sig = inspect.signature(think_tool.func)
    default = sig.parameters["max_iterations"].default
    assert default == 3, (
        f"think_tool.max_iterations default must remain 3. Got {default}."
    )


def test_think_tool_iteration_default_is_1():
    sig = inspect.signature(think_tool.func)
    default = sig.parameters["iteration"].default
    assert default == 1, (
        f"think_tool.iteration default must remain 1. Got {default}."
    )


def test_think_tool_signature_frozen():
    """Kwargs set is exactly {reflection, iteration, max_iterations, score_threshold}."""
    sig = inspect.signature(think_tool.func)
    kwargs = set(sig.parameters.keys())
    expected = {"reflection", "iteration", "max_iterations", "score_threshold"}
    assert kwargs == expected, (
        f"think_tool signature drifted: expected kwargs {expected}, got {kwargs}."
    )

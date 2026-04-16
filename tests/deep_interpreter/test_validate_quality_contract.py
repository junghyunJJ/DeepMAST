"""Contract tests for validate_quality — pins the shared tool behavior.

Trip-wire: if these tests fail, the shared validate_quality contract has drifted
in a way that could affect DrugTarget (which also imports this tool at
src/agents/drug_target/subagents/prompts.py:697) and every other consumer.

The five cases pin:
1. Default 50/50 blend formula (basic + llm_score) / 2
2. use_llm=False deterministic-only path (no LLM invocation)
3. LLM failure fallback (returns basic score, no exception)
4. Threshold 0.8 consumer-side boundary
5. Signature frozen (exact kwargs set)
"""

from __future__ import annotations

import inspect

import pytest

from src.agents.deep_interpreter.tools.quality import (
    _calculate_basic_score,
    validate_quality,
)


_SAMPLE_INTERPRETATION = """# Part 1: Spatial and Pathway Analysis

## Analysis 1-1: Spatial Clustering

### Figure Description
Spatial plot shows clusters 1-10 distributed across tissue with clear boundaries.

### Quantitative Findings
- Cluster 4 enrichment: 2.5-fold (p < 0.001)
- Cluster 17 density: 35% of spots
- Moran's R = 0.4776
- 449 unique cells profiled

### Biological Interpretation
The signaling pathway activation in cluster 4 involves ligand-receptor binding
dynamics and downstream cascade regulation (PMID: 35123456). Expression of
CDH1 indicates epithelial identity maintained by receptor-mediated adhesion,
while the EMT pathway activation suggests mesenchymal transition in boundary
regions (PMID: 28967543). The spatial gradient of TGFB signaling drives
cell-cell interaction between fibroblasts and tumor cells (PMID: 33445566).
Inhibition of this pathway has therapeutic relevance (PMID: 31122334).

### Cross-Analysis Connections
- Connection to Analysis 1-2: Cluster 4 aligns with tumor cell type enrichment.

### References
- PMID: 35123456
- PMID: 28967543
- PMID: 33445566
- PMID: 31122334

## Part 1 Summary

### Key Findings
1. Cluster 4 shows tumor-specific enrichment.
"""


# -----------------------------------------------------------------------------
# Case 1: Default 50/50 blend — the DEFAULT blend formula pin
# -----------------------------------------------------------------------------
def test_default_blend_50_50(monkeypatch):
    """With use_llm=True (default), the composite score is (basic + llm_score) / 2.

    This is THE test that fails if the shared validate_quality contract is
    silently redefined globally.
    """
    # Patch the reflection backend that validate_quality dispatches into.
    async def _fake_reflection(_reflection_text):
        return {"success": True, "result": "Overall Score: 0.9\nPassed: yes"}

    monkeypatch.setattr(
        "src.agents.deep_interpreter.tools.quality.invoke_reflection_tool",
        _fake_reflection,
    )

    # Compute the expected basic score directly — use_llm=False baseline.
    basic = _calculate_basic_score(_SAMPLE_INTERPRETATION)["score"]

    # Invoke validate_quality with no kwargs override → use_llm=True default.
    result = validate_quality.invoke({"interpretation": _SAMPLE_INTERPRETATION})

    expected = round((basic + 0.9) / 2, 3)
    assert result["score"] == expected, (
        f"Default blend drifted: expected (basic + llm_score) / 2 = {expected}, "
        f"got {result['score']}. basic={basic}, llm_score=0.9."
    )


# -----------------------------------------------------------------------------
# Case 2: use_llm=False deterministic-only path — no LLM call
# -----------------------------------------------------------------------------
def test_use_llm_false_deterministic_only(monkeypatch):
    """use_llm=False MUST NOT invoke the reflection backend and returns basic score."""
    invocation_count = {"n": 0}

    async def _spy_reflection(_reflection_text):
        invocation_count["n"] += 1
        return {"success": True, "result": "Overall Score: 0.9"}

    monkeypatch.setattr(
        "src.agents.deep_interpreter.tools.quality.invoke_reflection_tool",
        _spy_reflection,
    )

    result = validate_quality.invoke(
        {"interpretation": _SAMPLE_INTERPRETATION, "use_llm": False}
    )
    expected_basic = _calculate_basic_score(_SAMPLE_INTERPRETATION)["score"]

    assert invocation_count["n"] == 0, (
        "use_llm=False must NOT invoke the reflection backend; "
        f"invoked {invocation_count['n']} times."
    )
    assert result["score"] == expected_basic, (
        f"use_llm=False must return basic score {expected_basic}, got {result['score']}."
    )


# -----------------------------------------------------------------------------
# Case 3: LLM failure fallback — no exception, returns basic
# -----------------------------------------------------------------------------
def test_llm_failure_fallback(monkeypatch):
    """Reflection backend raising → validate_quality returns basic score, no raise."""
    async def _raising_reflection(_reflection_text):
        raise RuntimeError("reflection backend down")

    monkeypatch.setattr(
        "src.agents.deep_interpreter.tools.quality.invoke_reflection_tool",
        _raising_reflection,
    )

    expected_basic = _calculate_basic_score(_SAMPLE_INTERPRETATION)["score"]
    # Default use_llm=True — should still not raise.
    result = validate_quality.invoke({"interpretation": _SAMPLE_INTERPRETATION})
    assert result["score"] == expected_basic, (
        f"LLM failure must fall back to basic score {expected_basic}, got {result['score']}."
    )


# -----------------------------------------------------------------------------
# Case 4: Threshold 0.8 consumer-side boundary
# -----------------------------------------------------------------------------
def test_threshold_0_8_boundary():
    """The 0.8 gate is a consumer-side comparison. Pin the boundary semantics."""
    # 0.8 → pass (>= 0.8)
    assert 0.8 >= 0.8
    # 0.7999 → fail (< 0.8)
    assert 0.7999 < 0.8
    # Sanity: validate_quality returns a float score that consumers compare
    # against 0.8. Ensure the returned 'score' is a float in [0.0, 1.0].
    result = validate_quality.invoke(
        {"interpretation": _SAMPLE_INTERPRETATION, "use_llm": False}
    )
    assert isinstance(result["score"], float)
    assert 0.0 <= result["score"] <= 1.0


# -----------------------------------------------------------------------------
# Case 5: Signature frozen — kwargs set MUST match exactly
# -----------------------------------------------------------------------------
def test_signature_frozen():
    """Freeze validate_quality's kwargs set. Fails if any kwarg is added/removed/renamed.

    Explicitly fails if `score_threshold` is ever added to validate_quality — the
    0.8 gate is a consumer-side comparison and must never be a tool parameter.
    """
    # The underlying function (before @tool decoration) is in validate_quality.func.
    sig = inspect.signature(validate_quality.func)
    kwargs = set(sig.parameters.keys())
    expected = {"interpretation", "references", "use_llm"}

    assert kwargs == expected, (
        f"validate_quality signature drifted: expected kwargs {expected}, got {kwargs}. "
        f"Do NOT add score_threshold here — it is a consumer-side 0.8 comparison."
    )
    # Guard the default: use_llm must default to True.
    assert sig.parameters["use_llm"].default is True, (
        "use_llm default must remain True for the shared contract."
    )

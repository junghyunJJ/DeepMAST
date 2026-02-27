"""Drug Target Assessment Agent.

Independent DeepAgents-based agent for therapeutic target assessment.
Called as a tool from the Reporter subagent.

Architecture:
    Reporter subagent
      -> run_drug_target_assessment() tool
        -> DrugTargetAgent (2 subagents)
             evidence_assessor -> report_writer

Input: lr_candidates.json (top-15 L-R pairs) + selected_top3_lr.json + disease context
Output: drug.md (markdown for HTML report integration)
"""

def __getattr__(name):
    """Lazy imports to avoid circular dependency."""
    if name == "create_drug_target_agent":
        from src.agents.drug_target.agent import create_drug_target_agent
        return create_drug_target_agent
    if name == "DrugTargetConfig":
        from src.agents.drug_target.agent import DrugTargetConfig
        return DrugTargetConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "create_drug_target_agent",
    "DrugTargetConfig",
]

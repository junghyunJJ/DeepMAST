from __future__ import annotations

from src.agents.drug_target.agent import (
    DrugTargetConfig,
    _format_hypothesis_writer_resume_instruction,
)


def test_default_resume_instruction_points_to_data_dir() -> None:
    config = DrugTargetConfig(data_dir="/tmp/workspace")

    instruction = _format_hypothesis_writer_resume_instruction(
        config,
        "/tmp/workspace",
    )

    assert instruction == (
        "Generate hypotheses from evidence already on disk. Data dir: /tmp/workspace"
    )


def test_custom_resume_instruction_is_prompt_slot_safe() -> None:
    config = DrugTargetConfig(
        data_dir="/tmp/workspace",
        hypothesis_writer_resume_instruction='Line one\nUse "quoted" value',
    )

    instruction = _format_hypothesis_writer_resume_instruction(
        config,
        "/tmp/workspace",
    )

    assert instruction == "Line one Use 'quoted' value"

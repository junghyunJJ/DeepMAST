"""Summarizer wire-up regression for the deterministic finalizer.

The normal Summarizer must no longer be a prompt-driven nested supervisor with
mutating ``save_drug_md`` middleware.  It is a deterministic host Runnable that
owns build -> render -> validate -> critic -> repair -> finalization.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS
from src.agents.drug_target.subagents.summarizer.middleware import (
    AnnotationDensityMiddleware,
    DrugMdSaveSanitizerMiddleware,
    FrozenTemplateSpanMiddleware,
)


def _stub_runnable() -> MagicMock:
    stub = MagicMock(spec=["invoke", "ainvoke", "with_config"])
    stub.with_config.return_value = stub
    return stub


def _inner_subagents() -> list[dict[str, Any]]:
    return [
        {
            **SUBAGENT_CONFIGS["report_writer"],
            "tools": list(SUBAGENT_CONFIGS["report_writer"]["tools"]),
        },
        {
            **SUBAGENT_CONFIGS["critic"],
            "tools": list(SUBAGENT_CONFIGS["critic"]["tools"]),
        },
    ]


def test_create_summarizer_agent_returns_deterministic_runnable() -> None:
    from src.agents.drug_target.subagents.summarizer.agent import (
        DeterministicSummarizerRunnable,
        create_summarizer_agent,
    )

    with patch(
        "src.agents.drug_target.subagents.summarizer.agent.create_deep_agent",
        return_value=_stub_runnable(),
    ) as mock_create:
        agent = create_summarizer_agent(inner_subagents=_inner_subagents())

    assert isinstance(agent, DeterministicSummarizerRunnable)
    assert isinstance(agent, Runnable)
    assert mock_create.call_count == 2
    prompts = [call.kwargs.get("system_prompt", "") for call in mock_create.mock_calls]
    assert any("Report Writer" in prompt for prompt in prompts)
    assert any("read-only Critic" in prompt for prompt in prompts)


def test_normal_summarizer_does_not_wire_mutating_markdown_middleware() -> None:
    from src.agents.drug_target.subagents.summarizer.agent import create_summarizer_agent

    with patch(
        "src.agents.drug_target.subagents.summarizer.agent.create_deep_agent",
        return_value=_stub_runnable(),
    ) as mock_create:
        create_summarizer_agent(inner_subagents=_inner_subagents())

    forbidden = (
        DrugMdSaveSanitizerMiddleware,
        FrozenTemplateSpanMiddleware,
        AnnotationDensityMiddleware,
    )
    for call in mock_create.mock_calls:
        middleware = call.kwargs.get("middleware", [])
        assert not any(isinstance(item, forbidden) for item in middleware)


def test_normal_report_writer_tool_surface_excludes_direct_markdown_writes() -> None:
    tool_names = {
        getattr(tool, "name", "")
        for tool in SUBAGENT_CONFIGS["report_writer"]["tools"]
    }

    assert "save_report_expansions" in tool_names
    assert "save_drug_md" not in tool_names
    assert "build_evidence_summary" not in tool_names
    assert "render_drug_md_from_expansions" not in tool_names


def test_build_evidence_summary_does_not_write_root_drug_md(tmp_path: Path) -> None:
    import shutil

    from src.agents.drug_target.tools.stage_logic import build_evidence_summary

    fixture = Path(__file__).parent / "fixtures" / "clean"
    data_dir = tmp_path / "run"
    shutil.copytree(fixture, data_dir)
    (data_dir / "drug.md").unlink()

    raw = build_evidence_summary.invoke({"data_dir": str(data_dir)})

    assert "error" not in raw
    assert not (data_dir / "drug.md").exists()
    assert (data_dir / "drug_report_reference_card.json").exists()
    assert (data_dir / "drug_report_template.md").exists()


def test_deterministic_summarizer_persists_expansions_returned_by_writer(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.subagents.summarizer.agent import (
        DeterministicSummarizerRunnable,
    )
    from src.agents.drug_target.tools.report_expansion_schema import (
        persist_drug_report_reference_card,
    )

    (tmp_path / "evidence").mkdir()
    persist_drug_report_reference_card(
        tmp_path,
        {
            "markdown_template": "Intro\n\n<!-- EXPAND: Add summary -->\n",
            "expansion_slots": [
                {
                    "slot_id": "section:executive_summary|slot:add_summary",
                    "section": "executive_summary",
                    "slot": "add_summary",
                }
            ],
            "provenance_index": {
                "evidence/ot_CD4.json::clinical_drugs": {
                    "source_file": "evidence/ot_CD4.json",
                    "source_field": "clinical_drugs",
                    "source_class": "opentargets_clinical",
                    "source_value": ["ibalizumab"],
                }
            },
        },
    )
    expansions = {
        "schema_version": "report_expansions.v1",
        "template_id": "drug_report.md.j2",
        "reference_card_hash": "writer-placeholder",
        "slots": [
            {
                "slot_id": "section:executive_summary|slot:add_summary",
                "section_id": "executive_summary",
                "sentences": [
                    {
                        "text": "CD4 has clinical-drug evidence in the reference card. [source: clinical_drugs]",
                        "source_fields": ["clinical_drugs"],
                        "source_provenance": {
                            "source_file": "evidence/ot_CD4.json",
                            "source_field": "clinical_drugs",
                            "source_class": "opentargets_clinical",
                            "claim_type": "interpretation",
                        },
                        "interpretation": True,
                        "hedging_verbs_present": True,
                    }
                ],
            }
        ],
    }

    writer = _stub_runnable()
    writer.invoke.return_value = {
        "messages": [AIMessage(content="```json\n" + json.dumps(expansions) + "\n```")]
    }
    critic = _stub_runnable()
    critic.invoke.return_value = {
        "messages": [
            AIMessage(
                content=json.dumps(
                    {
                        "passed": True,
                        "severity_counts": {"P0": 0, "P1": 0, "P2": 0, "P3": 0},
                        "checked_gates": ["unit"],
                        "findings": [],
                        "repair_instructions": [],
                        "claim_verdicts": [],
                    }
                )
            )
        ]
    }

    def render(data_dir: str) -> dict[str, Any]:
        base = Path(data_dir)
        (base / "drug.md").write_text("# Report\n", encoding="utf-8")
        (base / "drug_report_render.json").write_text("{}", encoding="utf-8")
        return {"rendered": True}

    agent = DeterministicSummarizerRunnable(
        report_writer=writer,
        critic=critic,
        data_dir=str(tmp_path),
    )

    with (
        patch(
            "src.agents.drug_target.subagents.configs.filter_hypothesis_evidence_files",
            return_value=None,
        ),
        patch(
            "src.agents.drug_target.subagents.configs.write_critic_slices",
            return_value=None,
        ),
        patch(
            "src.agents.drug_target.subagents.configs.cleanup_critic_slices",
            return_value=None,
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.build_evidence_summary",
            lambda data_dir: {"ok": True},
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.render_drug_md_from_expansions",
            render,
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.validate_drug_md",
            lambda data_dir: {"valid": True, "issues": []},
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.validate_drug_report_finalization",
            lambda data_dir, require_critic=False: {"valid": True, "issue_count": 0},
        ),
    ):
        result = agent.invoke({"messages": []})

    content = result["messages"][-1].content
    saved = json.loads((tmp_path / "report_expansions.json").read_text(encoding="utf-8"))
    assert content.startswith("SUMMARIZER_STATUS: PASS"), content
    assert saved["reference_card_hash"] != "writer-placeholder"


def test_deterministic_summarizer_fails_empty_writer_payload_without_fallback(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.subagents.summarizer.agent import (
        DeterministicSummarizerRunnable,
    )
    from src.agents.drug_target.tools.report_expansion_schema import (
        persist_drug_report_reference_card,
    )

    (tmp_path / "evidence").mkdir()
    persist_drug_report_reference_card(
        tmp_path,
        {
            "markdown_template": "Intro\n\n<!-- EXPAND: Add summary -->\n",
            "expansion_slots": [
                {
                    "slot_id": "section:executive_summary|slot:add_summary",
                    "section": "executive_summary",
                    "slot": "add_summary",
                }
            ],
            "provenance_index": {
                "drug_report_reference_card.json::stage3_candidates": {
                    "source_file": "drug_report_reference_card.json",
                    "source_field": "stage3_candidates",
                    "source_class": "reference_card",
                    "source_value": ["CD4"],
                }
            },
        },
    )
    writer = _stub_runnable()
    writer.invoke.return_value = {
        "messages": [
            AIMessage(
                content=json.dumps(
                    {
                        "report_expansions_version": "v1",
                        "data_dir": str(tmp_path),
                        "reference_card_source": "drug_report_reference_card.json",
                        "expansions": {},
                    }
                )
            )
        ]
    }
    critic = _stub_runnable()
    critic.invoke.return_value = {
        "messages": [
            AIMessage(
                content=json.dumps(
                    {
                        "passed": True,
                        "severity_counts": {"P0": 0, "P1": 0, "P2": 0, "P3": 0},
                        "checked_gates": ["unit"],
                        "findings": [],
                        "repair_instructions": [],
                        "claim_verdicts": [],
                    }
                )
            )
        ]
    }

    def render(data_dir: str) -> dict[str, Any]:
        base = Path(data_dir)
        (base / "drug.md").write_text("# Report\n", encoding="utf-8")
        (base / "drug_report_render.json").write_text("{}", encoding="utf-8")
        return {"rendered": True}

    agent = DeterministicSummarizerRunnable(
        report_writer=writer,
        critic=critic,
        data_dir=str(tmp_path),
    )

    with (
        patch(
            "src.agents.drug_target.subagents.configs.filter_hypothesis_evidence_files",
            return_value=None,
        ),
        patch(
            "src.agents.drug_target.subagents.configs.write_critic_slices",
            return_value=None,
        ),
        patch(
            "src.agents.drug_target.subagents.configs.cleanup_critic_slices",
            return_value=None,
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.build_evidence_summary",
            lambda data_dir: {"ok": True},
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.render_drug_md_from_expansions",
            render,
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.validate_drug_md",
            lambda data_dir: {"valid": True, "issues": []},
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.validate_drug_report_finalization",
            lambda data_dir, require_critic=False: {"valid": True, "issue_count": 0},
        ),
    ):
        result = agent.invoke({"messages": []})

    content = result["messages"][-1].content
    assert content.startswith("SUMMARIZER_STATUS: FAIL"), content
    assert "report_writer did not create report_expansions.json" in content
    assert "WRITER_EXPANSIONS_JSON_INVALID" in content
    assert not (tmp_path / "report_expansions.json").exists()


def test_deterministic_summarizer_retries_initial_writer_contract_failure(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.subagents.summarizer.agent import (
        DeterministicSummarizerRunnable,
    )
    from src.agents.drug_target.tools.report_expansion_schema import (
        persist_drug_report_reference_card,
    )

    (tmp_path / "evidence").mkdir()
    persist_drug_report_reference_card(
        tmp_path,
        {
            "markdown_template": "Intro\n\n<!-- EXPAND: Add summary -->\n",
            "expansion_slots": [
                {
                    "slot_id": "section:executive_summary|slot:add_summary",
                    "section": "executive_summary",
                    "slot": "add_summary",
                }
            ],
            "provenance_index": {
                "drug_report_reference_card.json::stage3_candidates": {
                    "source_file": "drug_report_reference_card.json",
                    "source_field": "stage3_candidates",
                    "source_class": "reference_card",
                    "source_value": ["CD4"],
                }
            },
        },
    )
    expansions = {
        "schema_version": "report_expansions.v1",
        "slots": [
            {
                "slot_id": "section:executive_summary|slot:add_summary",
                "sentences": [
                    {
                        "text": "CD4 remains in the candidate set. [source: stage3_candidates]",
                        "source_fields": ["stage3_candidates"],
                        "source_provenance": {
                            "source_file": "drug_report_reference_card.json",
                            "source_field": "stage3_candidates",
                            "source_class": "reference_card",
                        },
                    }
                ],
            }
        ],
    }

    writer = _stub_runnable()
    writer.invoke.side_effect = [
        {
            "messages": [
                AIMessage(
                    content=json.dumps(
                        {
                            "report_expansions_version": "v1",
                            "status": "blocked",
                            "slots": [],
                        }
                    )
                )
            ]
        },
        {"messages": [AIMessage(content=json.dumps(expansions))]},
    ]
    critic = _stub_runnable()
    critic.invoke.return_value = {
        "messages": [
            AIMessage(
                content=json.dumps(
                    {
                        "passed": True,
                        "severity_counts": {"P0": 0, "P1": 0, "P2": 0, "P3": 0},
                        "checked_gates": ["unit"],
                        "findings": [],
                        "repair_instructions": [],
                        "claim_verdicts": [],
                    }
                )
            )
        ]
    }

    def render(data_dir: str) -> dict[str, Any]:
        base = Path(data_dir)
        (base / "drug.md").write_text("# Report\n", encoding="utf-8")
        (base / "drug_report_render.json").write_text("{}", encoding="utf-8")
        return {"rendered": True}

    agent = DeterministicSummarizerRunnable(
        report_writer=writer,
        critic=critic,
        data_dir=str(tmp_path),
    )

    with (
        patch(
            "src.agents.drug_target.subagents.configs.filter_hypothesis_evidence_files",
            return_value=None,
        ),
        patch(
            "src.agents.drug_target.subagents.configs.write_critic_slices",
            return_value=None,
        ),
        patch(
            "src.agents.drug_target.subagents.configs.cleanup_critic_slices",
            return_value=None,
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.build_evidence_summary",
            lambda data_dir: {"ok": True},
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.render_drug_md_from_expansions",
            render,
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.validate_drug_md",
            lambda data_dir: {"valid": True, "issues": []},
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.validate_drug_report_finalization",
            lambda data_dir, require_critic=False: {"valid": True, "issue_count": 0},
        ),
    ):
        result = agent.invoke({"messages": []})

    assert writer.invoke.call_count == 2
    assert result["messages"][-1].content.startswith("SUMMARIZER_STATUS: PASS")


def test_deterministic_summarizer_repairs_blocking_validate_findings(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.subagents.summarizer.agent import (
        DeterministicSummarizerRunnable,
    )
    from src.agents.drug_target.tools.report_expansion_schema import (
        persist_drug_report_reference_card,
    )

    (tmp_path / "evidence").mkdir()
    persist_drug_report_reference_card(
        tmp_path,
        {
            "markdown_template": "Intro\n\n<!-- EXPAND: Add summary -->\n",
            "expansion_slots": [
                {
                    "slot_id": "section:executive_summary|slot:add_summary",
                    "section": "executive_summary",
                    "slot": "add_summary",
                }
            ],
            "provenance_index": {
                "drug_report_reference_card.json::stage3_candidates": {
                    "source_file": "drug_report_reference_card.json",
                    "source_field": "stage3_candidates",
                    "source_class": "reference_card",
                    "source_value": ["CD4"],
                }
            },
        },
    )
    expansions = {
        "schema_version": "report_expansions.v1",
        "slots": [
            {
                "slot_id": "section:executive_summary|slot:add_summary",
                "sentences": [
                    {
                        "text": "CD4 remains in the candidate set. [source: stage3_candidates]",
                        "source_fields": ["stage3_candidates"],
                        "source_provenance": {
                            "source_file": "drug_report_reference_card.json",
                            "source_field": "stage3_candidates",
                            "source_class": "reference_card",
                        },
                    }
                ],
            }
        ],
    }
    writer = _stub_runnable()
    writer.invoke.side_effect = [
        {"messages": [AIMessage(content=json.dumps(expansions))]},
        {"messages": [AIMessage(content=json.dumps(expansions))]},
    ]
    critic = _stub_runnable()
    critic.invoke.return_value = {
        "messages": [
            AIMessage(
                content=json.dumps(
                    {
                        "passed": True,
                        "severity_counts": {"P0": 0, "P1": 0, "P2": 0, "P3": 0},
                        "checked_gates": ["unit"],
                        "findings": [],
                        "repair_instructions": [],
                        "claim_verdicts": [],
                    }
                )
            )
        ]
    }

    def render(data_dir: str) -> dict[str, Any]:
        base = Path(data_dir)
        (base / "drug.md").write_text("# Report\n", encoding="utf-8")
        (base / "drug_report_render.json").write_text("{}", encoding="utf-8")
        return {"rendered": True}

    validation_results = [
        {
            "valid": True,
            "issues": [],
            "findings": [
                {
                    "type": "FABRICATED_DRUG_NAME",
                    "snippet": "CD4 remains in the candidate set.",
                }
            ],
        },
        {"valid": True, "issues": [], "findings": []},
    ]
    agent = DeterministicSummarizerRunnable(
        report_writer=writer,
        critic=critic,
        data_dir=str(tmp_path),
    )

    with (
        patch(
            "src.agents.drug_target.subagents.configs.filter_hypothesis_evidence_files",
            return_value=None,
        ),
        patch(
            "src.agents.drug_target.subagents.configs.write_critic_slices",
            return_value=None,
        ),
        patch(
            "src.agents.drug_target.subagents.configs.cleanup_critic_slices",
            return_value=None,
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.build_evidence_summary",
            lambda data_dir: {"ok": True},
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.render_drug_md_from_expansions",
            render,
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.validate_drug_md",
            lambda data_dir: validation_results.pop(0),
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.validate_drug_report_finalization",
            lambda data_dir, require_critic=False: {"valid": True, "issue_count": 0},
        ),
    ):
        result = agent.invoke({"messages": []})

    assert writer.invoke.call_count == 2
    assert result["messages"][-1].content.startswith("SUMMARIZER_STATUS: PASS")


def test_deterministic_summarizer_fails_when_writer_returns_no_json(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.subagents.summarizer.agent import (
        DeterministicSummarizerRunnable,
    )
    from src.agents.drug_target.tools.report_expansion_schema import (
        persist_drug_report_reference_card,
    )

    (tmp_path / "evidence").mkdir()
    persist_drug_report_reference_card(
        tmp_path,
        {
            "stage3_candidates": ["CD4"],
            "markdown_template": "Intro\n\n<!-- EXPAND: Add summary -->\n",
            "expansion_slots": [
                {
                    "slot_id": "section:executive_summary|slot:add_summary",
                    "section": "executive_summary",
                    "slot": "add_summary",
                }
            ],
        },
    )
    (tmp_path / "report_expansions.json").write_text(
        json.dumps(
            {
                "schema_version": "report_expansions.v1",
                "reference_card_hash": "stale",
                "slots": [],
            }
        ),
        encoding="utf-8",
    )

    writer = _stub_runnable()
    writer.invoke.return_value = {"messages": [AIMessage(content="I wrote it.")]}
    agent = DeterministicSummarizerRunnable(
        report_writer=writer,
        critic=_stub_runnable(),
        data_dir=str(tmp_path),
    )

    result = agent._persist_writer_expansions(tmp_path, writer.invoke.return_value)

    assert result["saved"] is False, result
    assert result["errors"][0]["code"] == "WRITER_EXPANSIONS_JSON_MISSING"
    assert result["host_persisted_from_writer_json"] is False
    assert not (tmp_path / "report_expansions.json").exists()


def test_deterministic_summarizer_accepts_writer_saved_file_with_compact_final(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.subagents.summarizer.agent import (
        DeterministicSummarizerRunnable,
    )
    from src.agents.drug_target.tools.report_expansion_schema import (
        canonical_json_hash,
        persist_drug_report_reference_card,
        save_report_expansions,
    )

    (tmp_path / "evidence").mkdir()
    ref = persist_drug_report_reference_card(
        tmp_path,
        {
            "stage3_candidates": ["CD4"],
            "markdown_template": "Intro\n\n<!-- EXPAND: Add summary -->\n",
            "expansion_slots": [
                {
                    "slot_id": "section:executive_summary|slot:add_summary",
                    "section": "executive_summary",
                    "slot": "add_summary",
                }
            ],
            "provenance_index": {
                "drug_report_reference_card.json::stage3_candidates": {
                    "source_file": "drug_report_reference_card.json",
                    "source_field": "stage3_candidates",
                    "source_class": "reference_card",
                    "source_value": ["CD4"],
                }
            },
        },
    )
    saved = json.loads(
        save_report_expansions.invoke(
            {
                "data_dir": str(tmp_path),
                "expansions": {
                    "schema_version": "report_expansions.v1",
                    "reference_card_hash": canonical_json_hash(ref),
                    "slots": [
                        {
                            "slot_id": "section:executive_summary|slot:add_summary",
                            "sentences": [
                                {
                                    "text": "CD4 is retained in the reference-card candidate set.",
                                    "source_fields": ["stage3_candidates"],
                                    "source_provenance": {
                                        "source_file": "drug_report_reference_card.json",
                                        "source_field": "stage3_candidates",
                                        "source_class": "reference_card",
                                    },
                                }
                            ],
                        }
                    ],
                },
            }
        )
    )
    assert saved["saved"] is True, saved

    agent = DeterministicSummarizerRunnable(
        report_writer=_stub_runnable(),
        critic=_stub_runnable(),
        data_dir=str(tmp_path),
    )

    result = agent._persist_writer_expansions(
        tmp_path,
        {"messages": [AIMessage(content='{"saved": true}')]},
        allow_writer_saved_file=True,
    )

    assert result["saved"] is True, result
    assert result["host_loaded_writer_saved_file"] is True


def test_deterministic_summarizer_prefers_valid_writer_saved_file_over_status_payload(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.subagents.summarizer.agent import (
        DeterministicSummarizerRunnable,
    )
    from src.agents.drug_target.tools.report_expansion_schema import (
        canonical_json_hash,
        persist_drug_report_reference_card,
        save_report_expansions,
    )

    (tmp_path / "evidence").mkdir()
    ref = persist_drug_report_reference_card(
        tmp_path,
        {
            "stage3_candidates": ["CD4"],
            "markdown_template": "Intro\n\n<!-- EXPAND: Add summary -->\n",
            "expansion_slots": [
                {
                    "slot_id": "section:executive_summary|slot:add_summary",
                    "section": "executive_summary",
                    "slot": "add_summary",
                }
            ],
            "provenance_index": {
                "drug_report_reference_card.json::stage3_candidates": {
                    "source_file": "drug_report_reference_card.json",
                    "source_field": "stage3_candidates",
                    "source_class": "reference_card",
                    "source_value": ["CD4"],
                }
            },
        },
    )
    saved = json.loads(
        save_report_expansions.invoke(
            {
                "data_dir": str(tmp_path),
                "expansions": {
                    "schema_version": "report_expansions.v1",
                    "reference_card_hash": canonical_json_hash(ref),
                    "slots": [
                        {
                            "slot_id": "section:executive_summary|slot:add_summary",
                            "sentences": [
                                {
                                    "text": "CD4 remains in the candidate set.",
                                    "source_fields": ["stage3_candidates"],
                                    "source_provenance": {
                                        "source_file": "drug_report_reference_card.json",
                                        "source_field": "stage3_candidates",
                                        "source_class": "reference_card",
                                    },
                                }
                            ],
                        }
                    ],
                },
            }
        )
    )
    assert saved["saved"] is True, saved

    agent = DeterministicSummarizerRunnable(
        report_writer=_stub_runnable(),
        critic=_stub_runnable(),
        data_dir=str(tmp_path),
    )
    invalid_status_payload = {
        "messages": [
            AIMessage(
                content=json.dumps(
                    {
                        "report_expansions_version": "v1",
                        "status": "saved",
                        "path": str(tmp_path / "report_expansions.json"),
                        "slots": [],
                    }
                )
            )
        ]
    }

    result = agent._persist_writer_expansions(
        tmp_path,
        invalid_status_payload,
        allow_writer_saved_file=True,
    )

    assert result["saved"] is True, result
    assert result["host_loaded_writer_saved_file"] is True


def test_deterministic_summarizer_instructs_writer_to_save_expansions(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.subagents.summarizer.agent import (
        DeterministicSummarizerRunnable,
    )

    agent = DeterministicSummarizerRunnable(
        report_writer=_stub_runnable(),
        critic=_stub_runnable(),
        data_dir=str(tmp_path),
    )

    initial = agent._initial_writer_instruction(tmp_path)
    repair = agent._repair_writer_instruction(
        tmp_path,
        validation={"valid": False},
        critic_report={"passed": False},
        repair_index=1,
    )

    assert "MUST call save_report_expansions" in initial
    assert "MUST call save_report_expansions" in repair
    assert "Required call shape" in initial
    assert "Required call shape" in repair
    assert "return a compact JSON status" in initial
    assert "return a compact JSON status" in repair
    assert "Do not use file-edit or patch tools" in initial
    assert "Do not use file-edit or patch tools" in repair
    assert "Do not use generic placeholder prose" in initial
    assert "Do not use generic placeholder prose" in repair


def test_deterministic_summarizer_instructs_critic_to_use_virtual_paths(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.subagents.summarizer.agent import (
        DeterministicSummarizerRunnable,
    )

    agent = DeterministicSummarizerRunnable(
        report_writer=_stub_runnable(),
        critic=_stub_runnable(),
        data_dir=str(tmp_path),
    )

    instruction = agent._critic_instruction(
        tmp_path,
        validation={
            "valid": True,
            "location": str(tmp_path / "drug.md"),
        },
        render_result={
            "rendered": True,
            "path": str(tmp_path / "drug_report_render.json"),
        },
        label="initial",
    )

    assert str(tmp_path) not in instruction
    assert "host absolute paths" in instruction
    assert "/drug.md" in instruction
    assert "/drug_report_render.json" in instruction
    assert "/report_expansions.json" in instruction
    assert "/drug_report_reference_card.json" in instruction
    assert "/evidence/resolved_drugs.json" in instruction
    assert "/evidence/_critic_slices/" in instruction
    assert "Set passed=false only for P0/P1" in instruction
    assert "Section 4 template fields copied from /evidence/_critic_slices/_hypothesis.json" in instruction
    assert "must not be classified as FABRICATED_DRUG_NAME" in instruction


def test_critic_contradiction_detection_flags_absent_validator_finding() -> None:
    from src.agents.drug_target.subagents.summarizer.agent import (
        _critic_validation_contradictions,
    )

    report = {
        "passed": False,
        "severity_counts": {"P0": 0, "P1": 1, "P2": 1, "P3": 0},
        "findings": [
            {
                "severity": "P1",
                "issue": "validate_drug_md reported FABRICATED_DRUG_NAME for the scope note",
                "evidence": "validator flagged disease_scope as FABRICATED_DRUG_NAME",
                "source_field": "disease_scope",
            },
            {
                "severity": "P2",
                "issue": "Advisory wording issue",
                "evidence": "Non-blocking style concern.",
            },
        ],
        "claim_verdicts": [],
    }

    contradictions = _critic_validation_contradictions(report, {"valid": True, "issues": []})

    assert contradictions
    assert contradictions[0]["severity"] == "P1"
    assert "FABRICATED_DRUG_NAME" in contradictions[0]["claimed_validator_types"]


def test_critic_contradiction_detection_allows_real_validator_finding() -> None:
    from src.agents.drug_target.subagents.summarizer.agent import (
        _critic_validation_contradictions,
    )

    report = {
        "passed": False,
        "severity_counts": {"P0": 0, "P1": 1, "P2": 0, "P3": 0},
        "findings": [
            {
                "severity": "P1",
                "issue": "validate_drug_md reported FABRICATED_DRUG_NAME",
                "evidence": "validator reported FABRICATED_DRUG_NAME",
            },
        ],
        "claim_verdicts": [],
    }
    validation = {
        "valid": False,
        "issues": [
            {
                "code": "VALIDATE_DRUG_MD_BLOCKING_FINDING",
                "evidence": {"type": "FABRICATED_DRUG_NAME"},
            }
        ],
    }

    contradictions = _critic_validation_contradictions(report, validation)

    assert contradictions == []


def test_deterministic_summarizer_retries_contradictory_critic_output(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.subagents.summarizer.agent import (
        DeterministicSummarizerRunnable,
    )

    (tmp_path / "evidence").mkdir()
    critic = _stub_runnable()
    critic.invoke.side_effect = [
        {
            "messages": [
                AIMessage(
                    content=json.dumps(
                        {
                            "passed": False,
                            "severity_counts": {"P0": 0, "P1": 1, "P2": 0, "P3": 0},
                            "findings": [
                                {
                                    "severity": "P1",
                                    "issue": "validate_drug_md reported FABRICATED_DRUG_NAME for disease_scope",
                                    "evidence": "validator flagged FABRICATED_DRUG_NAME",
                                }
                            ],
                            "repair_instructions": [],
                            "claim_verdicts": [],
                        }
                    )
                )
            ]
        },
        {
            "messages": [
                AIMessage(
                    content=json.dumps(
                        {
                            "passed": True,
                            "severity_counts": {"P0": 0, "P1": 0, "P2": 0, "P3": 0},
                            "findings": [],
                            "repair_instructions": [],
                            "claim_verdicts": [],
                        }
                    )
                )
            ]
        },
    ]
    agent = DeterministicSummarizerRunnable(
        report_writer=_stub_runnable(),
        critic=critic,
        data_dir=str(tmp_path),
    )

    report = agent._run_critic(
        tmp_path,
        validation={"valid": True, "issues": [], "findings": []},
        render_result={"rendered": True},
        label="initial",
        config=None,
        write_critic_slices=lambda data_dir: None,
        cleanup_critic_slices=lambda data_dir: None,
    )

    assert critic.invoke.call_count == 2
    assert report["passed"] is True
    saved = json.loads((tmp_path / "evidence" / "critic_report.json").read_text(encoding="utf-8"))
    assert saved["passed"] is True
    assert "host_critic_contradictions" not in saved


def test_deterministic_summarizer_keeps_repeated_critic_contradiction_blocking(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.subagents.summarizer.agent import (
        DeterministicSummarizerRunnable,
    )

    (tmp_path / "evidence").mkdir()
    contradictory = {
        "passed": False,
        "severity_counts": {"P0": 0, "P1": 1, "P2": 0, "P3": 0},
        "findings": [
            {
                "severity": "P1",
                "issue": "validate_drug_md reported FABRICATED_DRUG_NAME for disease_scope",
                "evidence": "validator flagged FABRICATED_DRUG_NAME",
            }
        ],
        "repair_instructions": [],
        "claim_verdicts": [],
    }
    critic = _stub_runnable()
    critic.invoke.side_effect = [
        {"messages": [AIMessage(content=json.dumps(contradictory))]},
        {"messages": [AIMessage(content=json.dumps(contradictory))]},
    ]
    agent = DeterministicSummarizerRunnable(
        report_writer=_stub_runnable(),
        critic=critic,
        data_dir=str(tmp_path),
    )

    report = agent._run_critic(
        tmp_path,
        validation={"valid": True, "issues": [], "findings": []},
        render_result={"rendered": True},
        label="initial",
        config=None,
        write_critic_slices=lambda data_dir: None,
        cleanup_critic_slices=lambda data_dir: None,
    )

    assert report["passed"] is False
    assert report["severity_counts"]["P0"] == 1
    assert report["host_critic_contradictions"]


def test_validation_has_blockers_detects_blocking_findings() -> None:
    from src.agents.drug_target.subagents.summarizer.agent import (
        _validation_has_blockers,
    )

    assert _validation_has_blockers(
        {
            "valid": True,
            "issues": [],
            "findings": [{"type": "FABRICATED_DRUG_NAME"}],
        }
    )
    assert not _validation_has_blockers(
        {
            "valid": True,
            "issues": [],
            "findings": [{"type": "UNCITED_QUANTITATIVE"}],
        }
    )


def test_validation_has_blockers_ignores_renderer_external_false_positive(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.subagents.summarizer.agent import (
        _validation_has_blockers,
    )

    (tmp_path / "report_expansions.json").write_text(
        json.dumps(
            {
                "schema_version": "report_expansions.v1",
                "slots": [
                    {
                        "slot_id": "section:executive_summary|slot:add_summary",
                        "sentences": [
                            {
                                "text": "CD4 remains in the candidate set.",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert not _validation_has_blockers(
        {
            "valid": True,
            "issues": [],
            "findings": [
                {
                    "type": "FABRICATED_DRUG_NAME",
                    "snippet": "Scope note: pulmonary fibrosis evidence is used as a proxy.",
                }
            ],
        },
        tmp_path,
    )

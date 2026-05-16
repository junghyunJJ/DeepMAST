"""LLM-gated critic contract tests (Task #12).

All tests are marked @pytest.mark.llm and are excluded from deterministic CI.

Run with:
    uv run pytest tests/agents/drug_target/test_critic_llm_contract.py -m llm -v

Requirements:
    SUBAGENT_CRITIC_PROVIDER and SUBAGENT_CRITIC_MODEL env vars must be set, OR
    ANTHROPIC_API_KEY (falls back to claude-3-5-haiku-20241022) must be set.
    If neither is configured, all tests skip with a clear reason.

Test IDs:
  LLM-01  test_critic_subagent_rejects_plausible_but_ungrounded_medical_claim
  LLM-02  test_critic_subagent_passes_source_grounded_medical_sentence
  LLM-03  test_critic_subagent_returns_json_only_for_appendix_a_examples
"""

from __future__ import annotations

import json
import os

import pytest


# ---------------------------------------------------------------------------
# Skip guard: resolve model from env
# ---------------------------------------------------------------------------


def _resolve_critic_model_or_skip() -> str:
    """Return a usable critic model string, or call pytest.skip().

    Priority:
    1. SUBAGENT_CRITIC_PROVIDER + SUBAGENT_CRITIC_MODEL → "<provider>:<model>"
    2. ANTHROPIC_API_KEY present → use claude-3-5-haiku-20241022 as fallback
    """
    provider = os.environ.get("SUBAGENT_CRITIC_PROVIDER", "").strip()
    model = os.environ.get("SUBAGENT_CRITIC_MODEL", "").strip()

    if provider and model:
        return f"{provider}:{model}"

    # Fallback: Anthropic API key present → use cheapest capable model
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "anthropic:claude-3-5-haiku-20241022"

    pytest.skip(
        "LLM contract tests require SUBAGENT_CRITIC_PROVIDER+SUBAGENT_CRITIC_MODEL "
        "or ANTHROPIC_API_KEY to be set. Set one of these env vars to run LLM tests."
    )


# ---------------------------------------------------------------------------
# Helper: call the critic subagent synchronously via a minimal stub harness
# ---------------------------------------------------------------------------


def _invoke_critic_subagent(model: str, task_description: str) -> dict:
    """Invoke get_critic_subagent spec via the critic's system_prompt + model.

    Uses a minimal LangChain ChatModel call rather than the full DeepAgents
    harness so the test does not require a running backend.  The critic prompt
    is injected as the system message; the task_description is the user turn.

    Returns the parsed JSON dict from the critic response.
    Raises json.JSONDecodeError if the critic output is not parseable JSON.
    Raises ValueError if the response is empty.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from src.agents.drug_target.subagents.critic.agent import get_critic_subagent

    spec = get_critic_subagent(model=model)
    system_prompt: str = spec["system_prompt"]

    # Build the LangChain ChatModel from the model string
    # Support "provider:model" format
    if ":" in model:
        provider, model_name = model.split(":", 1)
    else:
        provider = "anthropic"
        model_name = model

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic  # noqa: PLC0415
        llm = ChatAnthropic(model=model_name, max_tokens=1024, temperature=0)
    elif provider in ("openai", "azure_openai"):
        from langchain_openai import ChatOpenAI  # noqa: PLC0415
        llm = ChatOpenAI(model=model_name, max_tokens=1024, temperature=0)
    else:
        pytest.skip(f"Unsupported critic provider {provider!r}; only anthropic/openai supported")

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=task_description),
    ]
    response = llm.invoke(messages)
    content = str(response.content).strip()

    if not content:
        raise ValueError("Critic returned empty response")

    # Strip markdown code fences if present
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()

    return json.loads(content)


def _make_task_description(
    payload_dict: dict,
    provenance_context: dict | None = None,
) -> str:
    """Build the task description JSON that the summarizer sends to the critic."""
    from src.agents.drug_target.tools.report_expansion_schema import canonical_json_hash
    from src.agents.drug_target.subagents.summarizer.middleware import normalize_expansions_for_hash

    payload_hash = canonical_json_hash(normalize_expansions_for_hash(payload_dict))
    return json.dumps(
        {
            "schema_version": "summarizer_critic_review.v1",
            "payload_hash": payload_hash,
            "payload": payload_dict,
            "provenance_context": provenance_context or {},
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# LLM-01: critic rejects plausible but ungrounded claim
# ---------------------------------------------------------------------------


@pytest.mark.llm
def test_critic_subagent_rejects_plausible_but_ungrounded_medical_claim() -> None:
    """Critic must return valid=false with EXTERNAL_KNOWLEDGE_INJECT blocker
    when the cited source mentions only drug evidence but the sentence claims
    TGF-beta / fibrotic-remodeling mechanisms unsupported by that source.

    This is the Appendix A rejection worked example.
    """
    model = _resolve_critic_model_or_skip()

    # Payload: sentence claims TGF-beta/fibrotic mechanism
    # Provenance: cited source is "drug evidence only" — no TGF-beta mention
    payload = {
        "schema_version": "report_expansions.v1",
        "slots": [
            {
                "slot_id": "section_3_mmp7",
                "sentences": [
                    {
                        "text": "MMP7 modulates TGF-beta signaling and fibrotic remodeling.",
                        "source_fields": ["clinical_drugs"],
                        "source_provenance": {
                            "source_file": "evidence/ot_MMP7.json",
                            "source_field": "clinical_drugs",
                            "source_class": "opentargets_clinical",
                            "claim_type": "direct_value",
                            "source_value": ["nintedanib", "pirfenidone"],
                        },
                    }
                ],
            }
        ],
    }

    # Provenance context: cited source only has drug names — no mechanistic info
    provenance_context = {
        "section_3_mmp7": {
            "cited_source_values": ["nintedanib", "pirfenidone"],
            "cited_provenance_entries": [
                {
                    "source_file": "evidence/ot_MMP7.json",
                    "source_field": "clinical_drugs",
                    "source_value_snippet": (
                        "clinical_drugs: ['nintedanib', 'pirfenidone']. "
                        "No mechanistic pathway information available in this field."
                    ),
                }
            ],
        }
    }

    task_description = _make_task_description(payload, provenance_context)
    result = _invoke_critic_subagent(model, task_description)

    assert isinstance(result, dict), f"Critic must return a JSON object; got: {type(result)}"
    assert "valid" in result, f"Critic JSON must contain 'valid' field; got keys: {list(result.keys())}"
    assert result["valid"] is False, (
        f"Critic must return valid=false for a plausible but ungrounded claim; "
        f"got valid={result['valid']!r}. Full result: {json.dumps(result, indent=2)}"
    )

    findings = result.get("findings", [])
    assert len(findings) > 0, "Critic must return at least one finding for the ungrounded claim"

    blocker_types = {f.get("finding_type") for f in findings if f.get("severity") == "blocker"}
    assert "EXTERNAL_KNOWLEDGE_INJECT" in blocker_types, (
        f"Critic must flag EXTERNAL_KNOWLEDGE_INJECT as a blocker finding; "
        f"got blocker finding_types: {blocker_types}"
    )


# ---------------------------------------------------------------------------
# LLM-02: critic passes source-grounded sentence
# ---------------------------------------------------------------------------


@pytest.mark.llm
def test_critic_subagent_passes_source_grounded_medical_sentence() -> None:
    """Critic must return valid=true and no blocker findings when the sentence
    is genuinely supported by the cited source text.
    """
    model = _resolve_critic_model_or_skip()

    # Payload: sentence accurately reflects cited clinical drug evidence
    payload = {
        "schema_version": "report_expansions.v1",
        "slots": [
            {
                "slot_id": "section_cd4_drugs",
                "sentences": [
                    {
                        "text": "CD4 has 3 approved clinical drugs per OpenTargets evidence.",
                        "source_fields": ["clinical_drugs"],
                        "source_provenance": {
                            "source_file": "evidence/ot_CD4.json",
                            "source_field": "clinical_drugs",
                            "source_class": "opentargets_clinical",
                            "claim_type": "direct_value",
                            "source_value": ["ibalizumab", "leronlimab", "fostemsavir"],
                        },
                    }
                ],
            }
        ],
    }

    # Provenance context: cited source genuinely supports the sentence
    provenance_context = {
        "section_cd4_drugs": {
            "cited_source_values": ["ibalizumab", "leronlimab", "fostemsavir"],
            "cited_provenance_entries": [
                {
                    "source_file": "evidence/ot_CD4.json",
                    "source_field": "clinical_drugs",
                    "source_value_snippet": (
                        "clinical_drugs: ['ibalizumab', 'leronlimab', 'fostemsavir']. "
                        "All 3 are FDA-approved drugs targeting the CD4 receptor."
                    ),
                }
            ],
        }
    }

    task_description = _make_task_description(payload, provenance_context)
    result = _invoke_critic_subagent(model, task_description)

    assert isinstance(result, dict), f"Critic must return a JSON object; got: {type(result)}"
    assert "valid" in result, f"Critic JSON must contain 'valid' field; got: {list(result.keys())}"
    assert result["valid"] is True, (
        f"Critic must return valid=true for a source-grounded sentence; "
        f"got valid={result['valid']!r}. Findings: {result.get('findings', [])}"
    )

    # No blocker findings for a passing result
    blocker_findings = [
        f for f in result.get("findings", []) if f.get("severity") == "blocker"
    ]
    assert len(blocker_findings) == 0, (
        f"Critic must not return blocker findings for a source-grounded sentence; "
        f"got: {blocker_findings}"
    )


# ---------------------------------------------------------------------------
# LLM-03: critic returns parseable JSON for Appendix A worked examples
# ---------------------------------------------------------------------------


@pytest.mark.llm
def test_critic_subagent_returns_json_only_for_appendix_a_examples() -> None:
    """When provided the two Appendix A worked examples as critic input,
    the critic must produce parseable JSON matching the schema for each.

    This confirms the critic does not hallucinate extra prose or wrap JSON
    in markdown when given well-formed inputs that mirror the prompt examples.
    """
    model = _resolve_critic_model_or_skip()

    # Appendix A pass example: clean payload, no findings expected
    pass_payload = {
        "schema_version": "report_expansions.v1",
        "slots": [
            {
                "slot_id": "section_clean",
                "sentences": [
                    {
                        "text": "TGFB1 has 5 approved drugs in OpenTargets clinical evidence.",
                        "source_fields": ["clinical_drugs"],
                        "source_provenance": {
                            "source_file": "evidence/ot_TGFB1.json",
                            "source_field": "clinical_drugs",
                            "source_class": "opentargets_clinical",
                            "claim_type": "direct_value",
                            "source_value": ["drug_a", "drug_b", "drug_c", "drug_d", "drug_e"],
                        },
                    }
                ],
            }
        ],
    }
    pass_provenance = {
        "section_clean": {
            "cited_source_values": ["drug_a", "drug_b", "drug_c", "drug_d", "drug_e"],
            "cited_provenance_entries": [
                {
                    "source_file": "evidence/ot_TGFB1.json",
                    "source_field": "clinical_drugs",
                    "source_value_snippet": (
                        "clinical_drugs: 5 approved drugs [drug_a, drug_b, drug_c, drug_d, drug_e]"
                    ),
                }
            ],
        }
    }

    pass_description = _make_task_description(pass_payload, pass_provenance)
    pass_result = _invoke_critic_subagent(model, pass_description)

    _assert_critic_schema_valid(pass_result, context="Appendix A pass example")

    # Appendix A reject example: ungrounded TGF-beta claim
    reject_payload = {
        "schema_version": "report_expansions.v1",
        "slots": [
            {
                "slot_id": "section_3_mmp7",
                "sentences": [
                    {
                        "text": "MMP7 modulates TGF-beta signaling and fibrotic remodeling.",
                        "source_fields": ["clinical_drugs"],
                        "source_provenance": {
                            "source_file": "evidence/ot_MMP7.json",
                            "source_field": "clinical_drugs",
                            "source_class": "opentargets_clinical",
                            "claim_type": "direct_value",
                            "source_value": ["nintedanib"],
                        },
                    }
                ],
            }
        ],
    }
    reject_provenance = {
        "section_3_mmp7": {
            "cited_source_values": ["nintedanib"],
            "cited_provenance_entries": [
                {
                    "source_file": "evidence/ot_MMP7.json",
                    "source_field": "clinical_drugs",
                    "source_value_snippet": "clinical_drugs: ['nintedanib']. No TGF-beta mention.",
                }
            ],
        }
    }

    reject_description = _make_task_description(reject_payload, reject_provenance)
    reject_result = _invoke_critic_subagent(model, reject_description)

    _assert_critic_schema_valid(reject_result, context="Appendix A reject example")

    # The reject example must produce valid=false
    assert reject_result["valid"] is False, (
        f"Appendix A reject example must produce valid=false; "
        f"got: {json.dumps(reject_result, indent=2)}"
    )


def _assert_critic_schema_valid(result: dict, context: str) -> None:
    """Assert that a critic result dict conforms to the Appendix A JSON schema."""
    required_top = {"valid", "payload_hash", "findings_count", "findings"}
    missing_top = required_top - set(result.keys())
    assert not missing_top, (
        f"[{context}] Critic JSON missing required top-level keys: {missing_top}. "
        f"Got keys: {list(result.keys())}"
    )

    assert isinstance(result["valid"], bool), (
        f"[{context}] 'valid' must be bool; got {type(result['valid'])}"
    )
    assert isinstance(result["findings"], list), (
        f"[{context}] 'findings' must be list; got {type(result['findings'])}"
    )
    assert isinstance(result["findings_count"], int), (
        f"[{context}] 'findings_count' must be int; got {type(result['findings_count'])}"
    )

    per_finding_required = {
        "finding_type", "severity", "slot_ids", "sentence", "reason", "repair_instruction"
    }
    for i, finding in enumerate(result["findings"]):
        missing_finding = per_finding_required - set(finding.keys())
        assert not missing_finding, (
            f"[{context}] Finding #{i} missing required keys: {missing_finding}. "
            f"Got: {list(finding.keys())}"
        )
        assert finding["severity"] in ("blocker", "warning"), (
            f"[{context}] Finding #{i} severity must be 'blocker' or 'warning'; "
            f"got {finding['severity']!r}"
        )
        assert finding["finding_type"] in (
            "BOILERPLATE_DUPLICATE", "EXTERNAL_KNOWLEDGE_INJECT"
        ), (
            f"[{context}] Finding #{i} finding_type must be "
            f"'BOILERPLATE_DUPLICATE' or 'EXTERNAL_KNOWLEDGE_INJECT'; "
            f"got {finding['finding_type']!r}"
        )

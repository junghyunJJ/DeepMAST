"""Tests for the simplified summarizer subagent (2026-05-13 simplification).

These tests replace the 17-test legacy summarizer suite. They cover:

  TS-01: dict spec shape and required keys
  TS-02: exact 7-tool inventory
  TS-03: skill-name wiring under DrugTargetConfig
  TS-04: SummarizerFinalizationGuardMiddleware PASS path
         (generate_drug_html_report proceeds after validate_drug_md=valid)
  TS-05: SummarizerFinalizationGuardMiddleware FAIL path
         (generate_drug_html_report blocked when validate_drug_md=invalid
          or never called)
  TS-06: orchestrator contract — ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE still
         references SUMMARIZER_STATUS and dispatches summarizer by name.
  TS-07: save_report_expansions auto-derives reference_card_hash when the
         caller omits it (live-smoke regression — gpt-5.4 cannot compute
         canonical-JSON SHA256 from a partially-readable offloaded card).
  TS-08: save_report_expansions still rejects an explicit hash that does
         not match the on-disk reference card, with expected/supplied in
         the error payload for one-turn self-correction.
  TS-09: persist_drug_report_reference_card writes the small
         expansion_schema_spec.json companion file with required_slot_ids,
         example_sentence, and valid_provenance_keys so the LLM can
         discover the run-specific schema without parsing the large
         offloaded reference card (live-smoke regression #2 — gpt-5.4
         could not reverse-engineer the nested sentence/provenance shape
         from the opaque @tool signature).
  TS-10: save_report_expansions args_schema advertises the Pydantic
         ReportExpansionsPayload (structural shape) so LangChain @tool
         auto-description is no longer opaque.

TS-04/TS-05 unit-test the mechanical fail-closed gate directly at the
middleware layer — sufficient under the (b') decision to retain and adapt
``SummarizerFinalizationGuardMiddleware`` for the new tool surface.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from langchain_core.messages import ToolMessage

from src.agents.drug_target.agent import (
    ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE,
    DrugTargetConfig,
    _build_subagent_skill_name_map,
)
from src.agents.drug_target.subagents.summarizer import get_summarizer_subagent
from src.agents.drug_target.subagents.summarizer.middleware import (
    SummarizerFinalizationGuardMiddleware,
)
from src.agents.drug_target.tools.report_expansion_schema import (
    EXPANSION_SCHEMA_SPEC_FILE,
    ReportExpansionsPayload,
    build_expansion_schema_spec,
    canonical_json_hash,
    persist_drug_report_reference_card,
    save_report_expansions,
)


_REQUIRED_KEYS: frozenset[str] = frozenset(
    {"name", "description", "system_prompt", "tools", "middleware"}
)

_REQUIRED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "build_evidence_summary",
        "load_evidence_files",
        "save_report_expansions",
        "render_drug_md_from_expansions",
        "validate_drug_md",
        "generate_drug_html_report",
        "think_tool",
    }
)


def _build_tool_request(name: str, args: dict | None = None, tool_id: str = "t_1"):
    request = MagicMock()
    request.tool_call = {"name": name, "args": args or {}, "id": tool_id}
    return request


# ---------------------------------------------------------------------------
# TS-01
# ---------------------------------------------------------------------------

def test_summarizer_returns_dict_spec_with_required_keys() -> None:
    spec = get_summarizer_subagent()
    assert isinstance(spec, dict)
    assert frozenset(spec.keys()) == _REQUIRED_KEYS, (
        f"unexpected keys: {sorted(spec.keys())}"
    )
    assert spec["name"] == "summarizer"
    assert "SUMMARIZER_STATUS" in spec["system_prompt"]
    assert isinstance(spec["tools"], list)
    assert isinstance(spec["middleware"], list)


# ---------------------------------------------------------------------------
# TS-02
# ---------------------------------------------------------------------------

def test_summarizer_tools_are_exactly_the_seven_required() -> None:
    spec = get_summarizer_subagent()
    tool_names = {tool.name for tool in spec["tools"]}
    assert tool_names == _REQUIRED_TOOL_NAMES
    assert len(spec["tools"]) == 7
    # Middleware: only the adapted fail-closed gate is attached by the factory.
    mw_types = {type(m) for m in spec["middleware"]}
    assert SummarizerFinalizationGuardMiddleware in mw_types


# ---------------------------------------------------------------------------
# TS-03
# ---------------------------------------------------------------------------

def test_summarizer_skill_names_default_and_config_wiring() -> None:
    config = DrugTargetConfig()
    assert config.summarizer_skill_names == ("drug-target-reporting",)
    # Old field name no longer exists.
    assert not hasattr(config, "report_writer_skill_names")

    skill_map = _build_subagent_skill_name_map(config, enable_census=True)
    assert set(skill_map.keys()) == {
        "evidence_assessor",
        "hypothesis_writer",
        "summarizer",
    }
    assert skill_map["summarizer"] == ("drug-target-reporting",)


# ---------------------------------------------------------------------------
# TS-04 — PASS path through the mechanical gate
# ---------------------------------------------------------------------------

def test_finalization_guard_allows_html_after_validator_passes() -> None:
    """``generate_drug_html_report`` proceeds when ``validate_drug_md`` returned
    ``valid=true``."""
    guard = SummarizerFinalizationGuardMiddleware()

    validator_request = _build_tool_request("validate_drug_md", tool_id="v_1")
    validator_result = ToolMessage(
        content=json.dumps({"valid": True, "errors": []}),
        tool_call_id="v_1",
    )
    guard.wrap_tool_call(validator_request, lambda _r: validator_result)

    final_request = _build_tool_request(
        "generate_drug_html_report",
        args={"data_dir": "/tmp/x"},
        tool_id="g_1",
    )
    sentinel = ToolMessage(content="<html>...</html>", tool_call_id="g_1")
    result = guard.wrap_tool_call(final_request, lambda _r: sentinel)

    assert result is sentinel, "guard must pass through after valid=true"


# ---------------------------------------------------------------------------
# TS-05 — FAIL paths through the mechanical gate
# ---------------------------------------------------------------------------

def test_finalization_guard_blocks_html_when_validator_never_called() -> None:
    """``generate_drug_html_report`` is blocked if no ``validate_drug_md``
    call was observed beforehand."""
    guard = SummarizerFinalizationGuardMiddleware()

    final_request = _build_tool_request(
        "generate_drug_html_report",
        args={"data_dir": "/tmp/x"},
        tool_id="g_1",
    )
    handler_called = MagicMock()
    result = guard.wrap_tool_call(final_request, handler_called)

    assert isinstance(result, ToolMessage)
    payload = json.loads(str(result.content))
    assert payload["ok"] is False
    assert payload["blocked_by"] == "SummarizerFinalizationGuard"
    assert "validate_drug_md" in payload["error"]
    handler_called.assert_not_called()


def test_finalization_guard_blocks_html_when_validator_returned_invalid() -> None:
    """``generate_drug_html_report`` is blocked when the most recent
    ``validate_drug_md`` returned ``valid=false``."""
    guard = SummarizerFinalizationGuardMiddleware()

    validator_request = _build_tool_request("validate_drug_md", tool_id="v_1")
    validator_result = ToolMessage(
        content=json.dumps({"valid": False, "errors": ["WRONG_THING"]}),
        tool_call_id="v_1",
    )
    guard.wrap_tool_call(validator_request, lambda _r: validator_result)

    final_request = _build_tool_request(
        "generate_drug_html_report",
        args={"data_dir": "/tmp/x"},
        tool_id="g_1",
    )
    handler_called = MagicMock()
    result = guard.wrap_tool_call(final_request, handler_called)

    assert isinstance(result, ToolMessage)
    payload = json.loads(str(result.content))
    assert payload["ok"] is False
    assert "valid=false" in payload["error"]
    handler_called.assert_not_called()


# ---------------------------------------------------------------------------
# TS-06 — orchestrator contract preserved
# ---------------------------------------------------------------------------

def test_orchestrator_contract_unchanged() -> None:
    """The orchestrator still dispatches the ``summarizer`` subagent by name
    and parses the literal ``SUMMARIZER_STATUS:`` contract."""
    assert "SUMMARIZER_STATUS: PASS" in ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE
    assert "SUMMARIZER_STATUS: FAIL" in ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE
    assert 'subagent_type="summarizer"' in ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE
    # No lingering reference to the removed inner-subagent dispatch.
    assert 'subagent_type="report_writer"' not in ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE
    assert 'subagent_type="critic"' not in ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE


# ---------------------------------------------------------------------------
# Helpers for TS-07 / TS-08 — minimal reference card + expansions fixtures
# ---------------------------------------------------------------------------


def _write_minimal_reference_card(data_dir: Path) -> dict:
    """Write the smallest reference card that ``validate_report_expansions``
    will accept, plus a matching ``provenance_index`` entry. Returns the
    in-memory dict so tests can compute the expected canonical-JSON hash."""
    card = {
        "expansion_slots": [{"slot_id": "test_slot"}],
        "provenance_index": {
            "evidence/test.json::status": {
                "source_value": "ok",
                "source_class": "ot_target",
            },
        },
    }
    (data_dir / "drug_report_reference_card.json").write_text(
        json.dumps(card, indent=2), encoding="utf-8"
    )
    return card


def _minimal_expansions_payload() -> dict:
    """Single-slot, single-sentence payload that passes schema +
    provenance checks against ``_write_minimal_reference_card``."""
    return {
        "schema_version": "report_expansions.v1",
        "slots": [
            {
                "slot_id": "test_slot",
                "sentences": [
                    {
                        "text": "Status is ok.",
                        "source_fields": ["status"],
                        "source_provenance": {
                            "source_file": "evidence/test.json",
                            "source_field": "status",
                            "source_class": "ot_target",
                            "claim_type": "direct_value",
                            "source_value": "ok",
                        },
                    }
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# TS-07 — hash auto-derive (live-smoke regression)
# ---------------------------------------------------------------------------

def test_save_report_expansions_auto_derives_hash(tmp_path: Path) -> None:
    """``save_report_expansions`` must accept payloads that OMIT
    ``reference_card_hash`` and auto-derive the hash from the on-disk
    reference card. The persisted ``report_expansions.json`` then carries
    the derived hash, making the payload self-describing.

    Live-smoke regression: gpt-5.4 cannot compute canonical-JSON SHA256
    of a 3000-line offloaded reference card. The previous strict-required
    contract made the simplified summarizer unrunnable end-to-end.
    """
    card = _write_minimal_reference_card(tmp_path)
    expansions = _minimal_expansions_payload()
    # NOTE: no reference_card_hash key at all.
    assert "reference_card_hash" not in expansions

    raw = save_report_expansions.invoke(
        {"data_dir": str(tmp_path), "expansions": expansions}
    )
    result = json.loads(raw)

    assert result["saved"] is True, result
    assert result["errors"] == []

    expected_hash = canonical_json_hash(card)
    persisted = json.loads(
        (tmp_path / "report_expansions.json").read_text(encoding="utf-8")
    )
    assert persisted["reference_card_hash"] == expected_hash


# ---------------------------------------------------------------------------
# TS-08 — explicit-wrong-hash still rejected
# ---------------------------------------------------------------------------

def test_save_report_expansions_rejects_wrong_hash(tmp_path: Path) -> None:
    """When the caller DOES supply ``reference_card_hash`` and it does not
    match the on-disk reference card, ``save_report_expansions`` must reject
    with ``RENDER_SOURCE_HASH_MISMATCH`` and surface both ``expected`` and
    ``supplied`` so a misbehaving LLM can self-correct in one turn."""
    card = _write_minimal_reference_card(tmp_path)
    expansions = _minimal_expansions_payload()
    bogus_hash = "0" * 64
    expansions["reference_card_hash"] = bogus_hash

    raw = save_report_expansions.invoke(
        {"data_dir": str(tmp_path), "expansions": expansions}
    )
    result = json.loads(raw)

    assert result["saved"] is False
    hash_errors = [
        e for e in result["errors"]
        if e.get("code") == "RENDER_SOURCE_HASH_MISMATCH"
    ]
    assert len(hash_errors) == 1
    err = hash_errors[0]
    assert err["supplied"] == bogus_hash
    assert err["expected"] == canonical_json_hash(card)


# ---------------------------------------------------------------------------
# TS-09 — schema-discovery file is written alongside the reference card
# ---------------------------------------------------------------------------

def test_persist_reference_card_also_writes_expansion_schema_spec(
    tmp_path: Path,
) -> None:
    """``persist_drug_report_reference_card`` must write the compact
    ``expansion_schema_spec.json`` companion file. The summarizer LLM
    relies on this small (non-offloaded) file to discover run-specific
    slot IDs and the sentence/provenance shape — recorded as the
    remediation for the second live-smoke failure mode."""
    # A minimal reference card the summarizer would consume — featured_genes
    # populated so _build_provenance_index produces real entries.
    reference_card = {
        "reference_card_version": "2.0",
        "stage3_candidates": ["TGFB1"],
        "featured_genes": [
            {
                "gene": "TGFB1",
                "stage3": {
                    "clinical_drugs": [{"name": "DrugA"}],
                    "preclinical_compounds": [],
                },
            }
        ],
        "markdown_template": (
            "# Report\n\n## Executive Summary\n"
            "<!-- EXPAND: Therapeutic Opportunities -->\n"
        ),
        "hypothesis_data": {"hypotheses": []},
    }
    persist_drug_report_reference_card(tmp_path, reference_card)

    spec_path = tmp_path / EXPANSION_SCHEMA_SPEC_FILE
    assert spec_path.exists(), (
        f"persist_drug_report_reference_card must write {EXPANSION_SCHEMA_SPEC_FILE}"
    )

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    assert spec["schema_version"] == "report_expansions.v1"
    # Required slot IDs derived from expansion_slots
    assert isinstance(spec["required_slot_ids"], list)
    assert len(spec["required_slot_ids"]) >= 1
    # Example sentence has the full nested shape
    example = spec["example_sentence"]
    assert set(example.keys()) == {"text", "source_fields", "source_provenance"}
    assert set(example["source_provenance"].keys()) == {
        "source_file",
        "source_field",
        "source_class",
        "claim_type",
        "source_value",
    }
    # Valid provenance keys are present and anchored to real evidence files
    assert isinstance(spec["valid_provenance_keys"], list)
    assert any("evidence/ot_TGFB1.json::clinical_drugs" == k
               for k in spec["valid_provenance_keys"])


# ---------------------------------------------------------------------------
# TS-10 — Pydantic args_schema advertises the nested expansions shape
# ---------------------------------------------------------------------------

def test_save_report_expansions_args_schema_advertises_pydantic_payload() -> None:
    """LangChain @tool must surface the ReportExpansionsPayload structural
    shape on the args_schema so LLMs no longer face an opaque `dict`
    parameter. Verified by:
      (a) `args_schema.model_fields["expansions"]` resolves to the
          Pydantic payload model (or a JSON-schema reference to it)
      (b) the tool description (auto-generated from the @tool docstring)
          mentions both `slot_id` and `source_provenance` so the LLM gets
          schema hints in its tool catalogue.
    """
    args_schema = save_report_expansions.args_schema
    schema_json = args_schema.model_json_schema()
    # The Pydantic payload sub-models must be reachable through the args
    # schema — either by name in $defs or inlined under properties.
    schema_text = json.dumps(schema_json)
    for marker in (
        "ReportExpansionsPayload",
        "SlotItem",
        "SentenceItem",
        "SourceProvenance",
    ):
        assert marker in schema_text, (
            f"args_schema must advertise {marker} sub-model (LLM "
            f"schema discovery depends on it)"
        )

    # The tool description must reference the key concepts so the LLM's
    # tool catalogue is informative even before reading the docstring in
    # full.
    description = save_report_expansions.description
    assert "slot_id" in description
    assert "source_provenance" in description

    # And the Pydantic model rejects structurally-invalid payloads at the
    # boundary (before reaching validate_report_expansions). Empty
    # sentences list MUST be rejected by the model.
    try:
        ReportExpansionsPayload(
            schema_version="report_expansions.v1",
            slots=[{"slot_id": "test_slot", "sentences": []}],
        )
    except Exception as exc:  # pydantic.ValidationError
        msg = str(exc).lower()
        assert "sentences" in msg
    else:
        raise AssertionError(
            "ReportExpansionsPayload must reject empty `sentences` list"
        )

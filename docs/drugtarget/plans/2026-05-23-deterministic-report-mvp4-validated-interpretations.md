# Deterministic Report MVP4 Validated Interpretations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MVP4 harness/eval diagnostics plus opt-in, validated LLM interpretation snippets for deterministic drug-target reports.

**Architecture:** `report_data.json` remains the deterministic source of truth, and `drug.md` / `drug_report.html` remain template-rendered artifacts. LLM output is allowed only as small section/candidate/hypothesis snippets keyed to existing `EXPAND` locations; invalid or missing snippets are omitted without failing finalization. Harness diagnostics become the acceptance surface for artifact validity, no-LLM fallback success, source consistency, `target_assessment` validity, optional/legacy artifact presence, and interpretation acceptance/rejection.

**Tech Stack:** Python 3.11, pytest, Jinja2, LangChain `RunnableConfig`, existing `src.agents.model.create_llm`, existing drug-target fixtures under `tests/agents/drug_target/fixtures`.

---

## Scope

Included:
- Backward-compatible MVP4 fields in `report_harness_diagnostics.json`.
- Diagnostics aggregation for fixture/eval loops.
- Optional `report_interpretations.json` when interpretation generation is explicitly enabled.
- Mock-provider tests for accepted, rejected, missing, and disabled interpretations.
- Template rendering at existing `<!-- EXPAND: ... -->` slots, without exposing raw `EXPAND` markers in final `drug.md`.

Excluded:
- No production graph routing changes.
- No live LLM/provider-credential tests in the default suite.
- No LLM-written `report_data.json`, full `drug.md`, or `drug_report.html`.
- No evidence collection behavior changes.
- No legacy cleanup or deletion of `report_expansions.json`.
- No mutation of `res_ipf_*` result directories.

## File Structure

Create:
- `src/agents/drug_target/report_interpretations.py`
  Owns interpretation-card construction, opt-in detection, provider invocation, snippet validation, and `report_interpretations.json` payload shaping.
- `tests/agents/drug_target/test_report_interpretations_mvp4.py`
  Focused unit/integration tests for cards, validation, opt-in behavior, markdown insertion, and no-LLM fallback.
- `tests/agents/drug_target/test_report_harness_mvp4.py`
  Focused tests for new harness checks and diagnostics aggregation.

Modify:
- `src/agents/drug_target/deterministic_report.py`
  Accept optional interpretations in markdown rendering, call the interpretation layer only when opt-in, write `report_interpretations.json` only when enabled, and preserve existing deterministic fallback behavior.
- `src/agents/drug_target/report_harness.py`
  Add MVP4 diagnostic checks and aggregation while preserving existing MVP2 top-level fields and issue codes.
- `skills/drug-target-reporting/templates/drug_report.md.j2`
  Render accepted interpretation snippets at existing `EXPAND` locations.
- `src/agents/drug_target/templates/drug_report.md.j2`
  Keep package fallback byte-aligned with the repo-local template.
- `docs/drugtarget/plans/2026-05-22-deterministic-report-mvp2-harness.md` or a new MVP4 plan note only if reviewers need a durable PR scope document. Prefer not to edit old MVP2 docs unless necessary.

Do not modify:
- `src/agents/drug_target/super_graph.py`
- `src/agents/drug_target/agent.py`
- production evidence collection tools

## Data Contracts

### Interpretation Card

Each card is a small deterministic input to an optional provider:

```python
{
    "id": "executive_summary.opportunities",
    "kind": "section",
    "instruction": "Write 1-3 sentences summarizing key therapeutic opportunities.",
    "allowed_genes": ["FN1", "MUC1", "CD4"],
    "allowed_drugs": ["OCRIPLASMIN"],
    "allowed_numbers": ["41", "6", "15"],
    "allowed_sources": ["evidence/assessment_results.json"],
    "facts": {
        "disease": "idiopathic pulmonary fibrosis",
        "featured_genes": ["FN1", "MUC1", "CD4"],
    },
}
```

### Interpretation Payload

When enabled, write `report_interpretations.json` with this shape:

```python
{
    "schema_version": "drug_target.report_interpretations.v1",
    "enabled": True,
    "created_at": "2026-05-23T00:00:00+00:00",
    "summary": {
        "cards": 0,
        "accepted": 0,
        "rejected": 0,
        "missing": 0,
        "provider_errors": 0,
    },
    "snippets": {
        "executive_summary.opportunities": {
            "status": "accepted",
            "text": "FN1 and MUC1 anchor the highest-priority opportunities...",
            "issues": [],
        }
    },
}
```

Accepted snippets are copied into a render map:

```python
{
    "executive_summary_opportunities": "...",
    "scoring_landscape": "...",
    "stage1_filter": "...",
    "candidates": {
        "FN1": {
            "drug_profile": "...",
            "biological_context": "...",
            "recommendation": "...",
        }
    },
    "hypotheses_overview": "...",
    "hypotheses": {
        "1": {"implication": "..."}
    },
    "final_recommendations": "...",
}
```

## Task 1: Add Interpretation Card And Validation Module

**Files:**
- Create: `src/agents/drug_target/report_interpretations.py`
- Test: `tests/agents/drug_target/test_report_interpretations_mvp4.py`

- [ ] **Step 1: Write failing card-construction test**

Add this test to `tests/agents/drug_target/test_report_interpretations_mvp4.py`:

```python
from __future__ import annotations

import json
import shutil
from pathlib import Path


def _copy_baseline_workspace(tmp_path: Path) -> Path:
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "baseline_hallucinated"
    )
    workspace = tmp_path / "workspace"
    shutil.copytree(fixture, workspace)
    return workspace


def test_build_interpretation_cards_include_existing_expand_slots(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data
    from src.agents.drug_target.report_interpretations import build_interpretation_cards

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(str(workspace), "idiopathic pulmonary fibrosis")

    cards = build_interpretation_cards(report_data)
    card_ids = {card["id"] for card in cards}

    assert "executive_summary.opportunities" in card_ids
    assert "scoring_landscape" in card_ids
    assert "stage1_filter.interpretation" in card_ids
    assert "hypotheses.overview" in card_ids
    assert "final_recommendations" in card_ids
    assert any(card_id.startswith("candidate.") and card_id.endswith(".drug_profile") for card_id in card_ids)
    assert any(card_id.startswith("candidate.") and card_id.endswith(".biological_context") for card_id in card_ids)
    assert any(card_id.startswith("candidate.") and card_id.endswith(".recommendation") for card_id in card_ids)
    assert any(card_id.startswith("hypothesis.") and card_id.endswith(".implication") for card_id in card_ids)

    executive = next(card for card in cards if card["id"] == "executive_summary.opportunities")
    assert executive["kind"] == "section"
    assert "FN1" in executive["allowed_genes"]
    assert "evidence/assessment_results.json" in executive["allowed_sources"]
    assert executive["facts"]["disease"] == "idiopathic pulmonary fibrosis"
```

- [ ] **Step 2: Run failing test**

Run:

```bash
pytest tests/agents/drug_target/test_report_interpretations_mvp4.py::test_build_interpretation_cards_include_existing_expand_slots -q
```

Expected: fail with `ModuleNotFoundError: No module named 'src.agents.drug_target.report_interpretations'`.

- [ ] **Step 3: Add minimal card builder**

Create `src/agents/drug_target/report_interpretations.py`:

```python
"""Optional validated interpretation snippets for deterministic drug reports."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any


INTERPRETATIONS_SCHEMA_VERSION = "drug_target.report_interpretations.v1"
ENABLE_INTERPRETATIONS_ENV = "DEEPMAST_ENABLE_REPORT_INTERPRETATIONS"
ENABLE_INTERPRETATIONS_CONFIG_KEY = "enable_report_interpretations"
INTERPRETATION_PROVIDER_CONFIG_KEY = "report_interpretation_provider"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dict_list(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _string_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _candidate_genes(report_data: Mapping[str, Any]) -> list[str]:
    genes: list[str] = []
    for candidate in _dict_list(report_data.get("candidates")):
        gene = str(candidate.get("gene") or "").strip().upper()
        if gene and gene not in genes:
            genes.append(gene)
    return genes


def _featured_candidates(report_data: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates = _dict_list(report_data.get("candidates"))
    featured = [candidate for candidate in candidates if candidate.get("stage3_candidate")]
    return featured or candidates[:5]


def _candidate_drugs(candidate: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    for drug in _dict_list(candidate.get("drugs")):
        name = str(drug.get("name") or drug.get("drug_name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _candidate_numbers(candidate: Mapping[str, Any]) -> list[str]:
    scores = candidate.get("scores")
    values: list[str] = []
    if isinstance(scores, dict):
        values.extend(str(value) for value in scores.values() if value is not None)
    for key in ("clinical_drug_count", "preclinical_drug_count", "drug_count"):
        if candidate.get(key) is not None:
            values.append(str(candidate[key]))
    return sorted(set(values))


def _section_sources(report_data: Mapping[str, Any], section_id: str) -> list[str]:
    sections = report_data.get("sections")
    if not isinstance(sections, dict):
        return []
    section = sections.get(section_id)
    if not isinstance(section, dict):
        return []
    return _string_list(section.get("sources"))


def build_interpretation_cards(report_data: Mapping[str, Any]) -> list[dict[str, Any]]:
    disease = str(report_data.get("disease") or "").strip()
    all_genes = _candidate_genes(report_data)
    featured = _featured_candidates(report_data)
    featured_genes = [str(candidate.get("gene") or "").strip().upper() for candidate in featured]
    featured_genes = [gene for gene in featured_genes if gene]
    candidates = _dict_list(report_data.get("candidates"))
    hypotheses = _dict_list(report_data.get("hypotheses"))

    cards: list[dict[str, Any]] = [
        {
            "id": "executive_summary.opportunities",
            "kind": "section",
            "instruction": "Write 1-3 sentences summarizing key therapeutic opportunities.",
            "allowed_genes": featured_genes,
            "allowed_drugs": [],
            "allowed_numbers": [str(len(candidates)), str(len(featured_genes))],
            "allowed_sources": _section_sources(report_data, "executive_summary"),
            "facts": {"disease": disease, "featured_genes": featured_genes},
        },
        {
            "id": "scoring_landscape",
            "kind": "section",
            "instruction": "Write 1-3 sentences interpreting the scoring landscape.",
            "allowed_genes": all_genes,
            "allowed_drugs": [],
            "allowed_numbers": [str(len(candidates)), str(len(featured_genes))],
            "allowed_sources": _section_sources(report_data, "druggability_matrix"),
            "facts": {"disease": disease},
        },
        {
            "id": "stage1_filter.interpretation",
            "kind": "section",
            "instruction": "Write 1-3 sentences interpreting Stage 1 biological validation.",
            "allowed_genes": all_genes,
            "allowed_drugs": [],
            "allowed_numbers": [],
            "allowed_sources": ["evidence/stage1_filter_results.json", "evidence/stage1_evidence.json"],
            "facts": {"disease": disease},
        },
    ]

    for candidate in featured:
        gene = str(candidate.get("gene") or "").strip().upper()
        if not gene:
            continue
        base = {
            "allowed_genes": [gene],
            "allowed_drugs": _candidate_drugs(candidate),
            "allowed_numbers": _candidate_numbers(candidate),
            "allowed_sources": _string_list(candidate.get("sources")),
            "facts": {"disease": disease, "gene": gene},
        }
        cards.extend(
            [
                {"id": f"candidate.{gene}.drug_profile", "kind": "candidate", "instruction": "Describe known drugs and indications only.", **base},
                {"id": f"candidate.{gene}.biological_context", "kind": "candidate", "instruction": "Interpret Stage 1 biological context.", **base},
                {"id": f"candidate.{gene}.recommendation", "kind": "candidate", "instruction": "Write a short evidence-grounded therapeutic recommendation.", **base},
            ]
        )

    cards.append(
        {
            "id": "hypotheses.overview",
            "kind": "hypotheses",
            "instruction": "Write 1-3 sentences summarizing hypothesis themes.",
            "allowed_genes": all_genes,
            "allowed_drugs": [],
            "allowed_numbers": [str(len(hypotheses))],
            "allowed_sources": _section_sources(report_data, "hypotheses"),
            "facts": {"disease": disease, "hypothesis_count": len(hypotheses)},
        }
    )
    for hypothesis in hypotheses:
        rank = str(hypothesis.get("rank") or "")
        entities = hypothesis.get("biological_entities")
        entities = entities if isinstance(entities, dict) else {}
        cards.append(
            {
                "id": f"hypothesis.{rank}.implication",
                "kind": "hypothesis",
                "instruction": "Write 1-2 sentences on therapeutic implications of this hypothesis.",
                "allowed_genes": _string_list(entities.get("genes")),
                "allowed_drugs": _string_list(entities.get("drugs")),
                "allowed_numbers": [rank] if rank else [],
                "allowed_sources": _string_list(hypothesis.get("evidence_references")),
                "facts": {
                    "disease": disease,
                    "rank": rank,
                    "title": hypothesis.get("title"),
                    "core_claim": hypothesis.get("core_claim"),
                },
            }
        )

    cards.append(
        {
            "id": "final_recommendations",
            "kind": "section",
            "instruction": "Write 1-3 sentences recommending next deterministic follow-up steps.",
            "allowed_genes": featured_genes,
            "allowed_drugs": [],
            "allowed_numbers": [str(len(candidates)), str(len(featured_genes))],
            "allowed_sources": _section_sources(report_data, "candidate_deep_dives"),
            "facts": {"disease": disease, "featured_genes": featured_genes},
        }
    )
    return cards
```

- [ ] **Step 4: Run card test**

Run:

```bash
pytest tests/agents/drug_target/test_report_interpretations_mvp4.py::test_build_interpretation_cards_include_existing_expand_slots -q
```

Expected: pass.

- [ ] **Step 5: Write failing validation tests**

Append:

```python
def test_validate_interpretation_accepts_allowed_entities() -> None:
    from src.agents.drug_target.report_interpretations import validate_interpretation_text

    card = {
        "id": "executive_summary.opportunities",
        "allowed_genes": ["FN1", "MUC1"],
        "allowed_drugs": [],
        "allowed_numbers": ["41", "6"],
        "allowed_sources": ["evidence/assessment_results.json"],
    }

    issues = validate_interpretation_text(
        card,
        "FN1 and MUC1 define 2 prioritized adhesion targets in the deterministic matrix.",
    )

    assert issues == []


def test_validate_interpretation_rejects_unsupported_claim_tokens() -> None:
    from src.agents.drug_target.report_interpretations import validate_interpretation_text

    card = {
        "id": "executive_summary.opportunities",
        "allowed_genes": ["FN1"],
        "allowed_drugs": [],
        "allowed_numbers": ["41"],
        "allowed_sources": ["evidence/assessment_results.json"],
    }

    issues = validate_interpretation_text(
        card,
        "NINTEDANIB improves 99% outcomes through TGFB2 according to fabricated.json.",
    )

    assert {issue["code"] for issue in issues} >= {
        "UNSUPPORTED_ENTITY",
        "UNSUPPORTED_NUMBER",
        "UNSUPPORTED_SOURCE",
    }
```

- [ ] **Step 6: Run failing validation tests**

Run:

```bash
pytest tests/agents/drug_target/test_report_interpretations_mvp4.py::test_validate_interpretation_accepts_allowed_entities tests/agents/drug_target/test_report_interpretations_mvp4.py::test_validate_interpretation_rejects_unsupported_claim_tokens -q
```

Expected: fail with `ImportError` for `validate_interpretation_text`.

- [ ] **Step 7: Add conservative validator**

Append to `report_interpretations.py`:

```python
import re


_ENTITY_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9-]{2,}\b")
_SOURCE_RE = re.compile(r"\b[\w.-]+\.json\b")
_NUMBER_RE = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?(?:e[+-]?\d+)?%?")
_DOMAIN_TOKEN_ALLOWLIST = {
    "CCI",
    "IPF",
    "DNA",
    "RNA",
    "GWAS",
    "KEGG",
    "STRING",
    "CENSUS",
    "RR",
    "PPI",
    "L-R",
    "N/A",
    "FDA",
    "CHEMBL",
}


def _allowed_upper_values(values: object) -> set[str]:
    return {value.upper() for value in _string_list(values)}


def _allowed_source_basenames(values: object) -> set[str]:
    return {value.rsplit("/", 1)[-1] for value in _string_list(values)}


def validate_interpretation_text(card: Mapping[str, Any], text: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    stripped = text.strip()
    if not stripped:
        return [
            {
                "code": "EMPTY_INTERPRETATION",
                "severity": "low",
                "message": "Interpretation text is empty.",
                "card_id": card.get("id"),
            }
        ]
    if "<!--" in stripped or "EXPAND" in stripped:
        issues.append(
            {
                "code": "PLACEHOLDER_LEAK",
                "severity": "critical",
                "message": "Interpretation text contains template placeholder syntax.",
                "card_id": card.get("id"),
            }
        )

    allowed_entities = (
        _allowed_upper_values(card.get("allowed_genes"))
        | _allowed_upper_values(card.get("allowed_drugs"))
        | _DOMAIN_TOKEN_ALLOWLIST
    )
    for token in sorted(set(_ENTITY_TOKEN_RE.findall(stripped))):
        if token.startswith("CHEMBL"):
            continue
        if token not in allowed_entities:
            issues.append(
                {
                    "code": "UNSUPPORTED_ENTITY",
                    "severity": "critical",
                    "message": f"Unsupported entity token in interpretation: {token}",
                    "card_id": card.get("id"),
                    "token": token,
                }
            )

    allowed_sources = set(_string_list(card.get("allowed_sources")))
    allowed_basenames = _allowed_source_basenames(card.get("allowed_sources"))
    for source in sorted(set(_SOURCE_RE.findall(stripped))):
        if source not in allowed_sources and source not in allowed_basenames:
            issues.append(
                {
                    "code": "UNSUPPORTED_SOURCE",
                    "severity": "critical",
                    "message": f"Unsupported source reference in interpretation: {source}",
                    "card_id": card.get("id"),
                    "source": source,
                }
            )

    allowed_numbers = set(str(value) for value in _string_list(card.get("allowed_numbers")))
    for number in sorted(set(_NUMBER_RE.findall(stripped))):
        if number not in allowed_numbers:
            issues.append(
                {
                    "code": "UNSUPPORTED_NUMBER",
                    "severity": "critical",
                    "message": f"Unsupported numeric claim in interpretation: {number}",
                    "card_id": card.get("id"),
                    "number": number,
                }
            )

    return issues
```

- [ ] **Step 8: Run validation tests**

Run:

```bash
pytest tests/agents/drug_target/test_report_interpretations_mvp4.py::test_validate_interpretation_accepts_allowed_entities tests/agents/drug_target/test_report_interpretations_mvp4.py::test_validate_interpretation_rejects_unsupported_claim_tokens -q
```

Expected: pass.

- [ ] **Step 9: Commit Task 1**

```bash
git add src/agents/drug_target/report_interpretations.py tests/agents/drug_target/test_report_interpretations_mvp4.py
git commit -m "Validate optional report interpretation cards

Constraint: MVP4 may enrich report prose but deterministic report_data remains the source of truth.
Rejected: Full-report LLM authoring | reopens the MVP1-3 finalizer failure mode.
Confidence: medium
Scope-risk: moderate
Directive: Keep interpretation validation conservative and provider-free in default tests.
Tested: pytest tests/agents/drug_target/test_report_interpretations_mvp4.py -q
Not-tested: Live provider calls."
```

## Task 2: Add Opt-In Provider Invocation And Payload Shaping

**Files:**
- Modify: `src/agents/drug_target/report_interpretations.py`
- Test: `tests/agents/drug_target/test_report_interpretations_mvp4.py`

- [ ] **Step 1: Write failing opt-in and generation tests**

Append:

```python
import asyncio


def test_report_interpretations_disabled_by_default(monkeypatch) -> None:
    from src.agents.drug_target.report_interpretations import report_interpretations_enabled

    monkeypatch.delenv("DEEPMAST_ENABLE_REPORT_INTERPRETATIONS", raising=False)

    assert report_interpretations_enabled({}) is False


def test_report_interpretations_enabled_by_config(monkeypatch) -> None:
    from src.agents.drug_target.report_interpretations import report_interpretations_enabled

    monkeypatch.delenv("DEEPMAST_ENABLE_REPORT_INTERPRETATIONS", raising=False)

    assert report_interpretations_enabled(
        {"configurable": {"enable_report_interpretations": True}}
    ) is True


def test_generate_interpretations_accepts_and_rejects_mock_provider(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data
    from src.agents.drug_target.report_interpretations import generate_report_interpretations

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(str(workspace), "idiopathic pulmonary fibrosis")

    def provider(card):
        if card["id"] == "executive_summary.opportunities":
            return "FN1 anchors a deterministic opportunity in the 41-gene assessment."
        if card["id"] == "scoring_landscape":
            return "NINTEDANIB creates 99% unsupported benefit from fabricated.json."
        return ""

    payload, render_map = asyncio.run(
        generate_report_interpretations(report_data, provider=provider)
    )

    assert payload["schema_version"] == "drug_target.report_interpretations.v1"
    assert payload["summary"]["accepted"] == 1
    assert payload["summary"]["rejected"] >= 1
    assert payload["summary"]["missing"] >= 1
    assert render_map["executive_summary_opportunities"].startswith("FN1 anchors")
    assert "scoring_landscape" not in render_map
    rejected = payload["snippets"]["scoring_landscape"]
    assert rejected["status"] == "rejected"
    assert {issue["code"] for issue in rejected["issues"]} >= {
        "UNSUPPORTED_ENTITY",
        "UNSUPPORTED_NUMBER",
        "UNSUPPORTED_SOURCE",
    }
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
pytest tests/agents/drug_target/test_report_interpretations_mvp4.py::test_report_interpretations_disabled_by_default tests/agents/drug_target/test_report_interpretations_mvp4.py::test_report_interpretations_enabled_by_config tests/agents/drug_target/test_report_interpretations_mvp4.py::test_generate_interpretations_accepts_and_rejects_mock_provider -q
```

Expected: fail because functions are missing.

- [ ] **Step 3: Add opt-in and generation functions**

Append:

```python
import inspect
import os
from collections.abc import Callable


def report_interpretations_enabled(config: Mapping[str, Any] | None) -> bool:
    configurable = config.get("configurable", {}) if isinstance(config, Mapping) else {}
    if isinstance(configurable, Mapping) and configurable.get(ENABLE_INTERPRETATIONS_CONFIG_KEY) is True:
        return True
    return os.getenv(ENABLE_INTERPRETATIONS_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _render_key(card_id: str) -> tuple[str, str | None, str | None]:
    parts = card_id.split(".")
    if card_id == "executive_summary.opportunities":
        return "executive_summary_opportunities", None, None
    if card_id == "scoring_landscape":
        return "scoring_landscape", None, None
    if card_id == "stage1_filter.interpretation":
        return "stage1_filter", None, None
    if card_id == "hypotheses.overview":
        return "hypotheses_overview", None, None
    if card_id == "final_recommendations":
        return "final_recommendations", None, None
    if len(parts) == 3 and parts[0] == "candidate":
        return "candidates", parts[1], parts[2]
    if len(parts) == 3 and parts[0] == "hypothesis":
        return "hypotheses", parts[1], parts[2]
    return card_id.replace(".", "_"), None, None


def _put_render_text(render_map: dict[str, Any], card_id: str, text: str) -> None:
    top_key, entity_key, leaf_key = _render_key(card_id)
    if entity_key is None or leaf_key is None:
        render_map[top_key] = text
        return
    container = render_map.setdefault(top_key, {})
    entity = container.setdefault(entity_key, {})
    entity[leaf_key] = text


async def _call_provider(provider: Callable[[dict[str, Any]], Any], card: dict[str, Any]) -> str:
    value = provider(card)
    if inspect.isawaitable(value):
        value = await value
    return str(value or "").strip()


async def generate_report_interpretations(
    report_data: Mapping[str, Any],
    provider: Callable[[dict[str, Any]], Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    cards = build_interpretation_cards(report_data)
    snippets: dict[str, dict[str, Any]] = {}
    render_map: dict[str, Any] = {}
    summary = {
        "cards": len(cards),
        "accepted": 0,
        "rejected": 0,
        "missing": 0,
        "provider_errors": 0,
    }

    for card in cards:
        card_id = str(card["id"])
        try:
            text = await _call_provider(provider, card)
        except Exception as exc:
            summary["provider_errors"] += 1
            snippets[card_id] = {
                "status": "provider_error",
                "text": "",
                "issues": [
                    {
                        "code": "INTERPRETATION_PROVIDER_ERROR",
                        "severity": "low",
                        "message": str(exc),
                        "card_id": card_id,
                    }
                ],
            }
            continue

        if not text:
            summary["missing"] += 1
            snippets[card_id] = {"status": "missing", "text": "", "issues": []}
            continue

        issues = validate_interpretation_text(card, text)
        if issues:
            summary["rejected"] += 1
            snippets[card_id] = {"status": "rejected", "text": text, "issues": issues}
            continue

        summary["accepted"] += 1
        snippets[card_id] = {"status": "accepted", "text": text, "issues": []}
        _put_render_text(render_map, card_id, text)

    return (
        {
            "schema_version": INTERPRETATIONS_SCHEMA_VERSION,
            "enabled": True,
            "created_at": _utc_now(),
            "summary": summary,
            "snippets": snippets,
        },
        render_map,
    )
```

- [ ] **Step 4: Run opt-in/generation tests**

Run:

```bash
pytest tests/agents/drug_target/test_report_interpretations_mvp4.py::test_report_interpretations_disabled_by_default tests/agents/drug_target/test_report_interpretations_mvp4.py::test_report_interpretations_enabled_by_config tests/agents/drug_target/test_report_interpretations_mvp4.py::test_generate_interpretations_accepts_and_rejects_mock_provider -q
```

Expected: pass.

- [ ] **Step 5: Run full interpretation tests**

Run:

```bash
pytest tests/agents/drug_target/test_report_interpretations_mvp4.py -q
```

Expected: pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/agents/drug_target/report_interpretations.py tests/agents/drug_target/test_report_interpretations_mvp4.py
git commit -m "Gate optional report interpretation generation

Constraint: Default deterministic finalization must remain provider-free.
Rejected: Environment-only activation | tests and graph callers need explicit config opt-in.
Confidence: medium
Scope-risk: moderate
Directive: Treat provider errors as snippet failures, not finalizer failures.
Tested: pytest tests/agents/drug_target/test_report_interpretations_mvp4.py -q
Not-tested: Live LLM provider invocation."
```

## Task 3: Render Accepted Snippets In The Deterministic Template

**Files:**
- Modify: `src/agents/drug_target/deterministic_report.py`
- Modify: `skills/drug-target-reporting/templates/drug_report.md.j2`
- Modify: `src/agents/drug_target/templates/drug_report.md.j2`
- Test: `tests/agents/drug_target/test_report_interpretations_mvp4.py`

- [ ] **Step 1: Write failing render insertion test**

Append:

```python
def test_render_report_markdown_inserts_accepted_interpretations(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import (
        build_report_data,
        render_report_markdown,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(str(workspace), "idiopathic pulmonary fibrosis")
    markdown = render_report_markdown(
        report_data,
        interpretations={
            "executive_summary_opportunities": "FN1 anchors a deterministic opportunity.",
            "scoring_landscape": "The scoring matrix prioritizes validated adhesion targets.",
            "stage1_filter": "Stage 1 separates biologically supported interactions from lower-confidence pairs.",
            "candidates": {
                "FN1": {
                    "drug_profile": "FN1 drug evidence is summarized from deterministic OpenTargets rows.",
                    "biological_context": "FN1-associated pairs provide the matrix context for interpretation.",
                    "recommendation": "FN1 should remain a prioritized evidence-review candidate.",
                }
            },
            "hypotheses_overview": "The retained hypotheses emphasize immune-retention and matrix-remodeling programs.",
            "hypotheses": {
                "1": {"implication": "This hypothesis supports focused validation of immune-retention mechanisms."}
            },
            "final_recommendations": "Follow-up should prioritize validated targets before lower-confidence exploratory genes.",
        },
    )

    assert "FN1 anchors a deterministic opportunity." in markdown
    assert "FN1 drug evidence is summarized from deterministic OpenTargets rows." in markdown
    assert "This hypothesis supports focused validation" in markdown
    assert "Follow-up should prioritize validated targets" in markdown
    assert "<!-- EXPAND:" not in markdown
```

- [ ] **Step 2: Run failing render test**

Run:

```bash
pytest tests/agents/drug_target/test_report_interpretations_mvp4.py::test_render_report_markdown_inserts_accepted_interpretations -q
```

Expected: fail because `render_report_markdown()` does not accept `interpretations`.

- [ ] **Step 3: Update markdown context signature**

Modify `src/agents/drug_target/deterministic_report.py`:

```python
import copy
```

Change:

```python
def _markdown_template_context(report_data: dict[str, Any]) -> dict[str, Any]:
```

to:

```python
def _markdown_template_context(
    report_data: dict[str, Any],
    interpretations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    interpretations = interpretations or {}
```

Inside the featured-card loop, after `gene = _safe_text(candidate.get("gene"), "")`, add:

```python
        candidate_interpretations = {}
        raw_candidate_interpretations = interpretations.get("candidates")
        if isinstance(raw_candidate_interpretations, dict):
            value = raw_candidate_interpretations.get(gene)
            if isinstance(value, dict):
                candidate_interpretations = value
```

Add this field to the `featured_cards.append(...)` dict:

```python
                "_interpretations": candidate_interpretations,
```

Replace hypothesis context loading:

```python
    hypothesis_data = template_context.get("hypothesis_data", {})
    hypothesis_data = hypothesis_data if isinstance(hypothesis_data, dict) else {}
```

with:

```python
    hypothesis_data = template_context.get("hypothesis_data", {})
    hypothesis_data = (
        copy.deepcopy(hypothesis_data)
        if isinstance(hypothesis_data, dict)
        else {}
    )
    raw_hypothesis_interpretations = interpretations.get("hypotheses")
    if isinstance(raw_hypothesis_interpretations, dict):
        for hypothesis in _dict_list(hypothesis_data.get("hypotheses", [])):
            rank = str(hypothesis.get("rank") or "")
            value = raw_hypothesis_interpretations.get(rank)
            if isinstance(value, dict):
                hypothesis["_interpretation"] = value.get("implication", "")
```

Add to the returned context:

```python
        "interpretations": interpretations,
```

Change:

```python
def render_report_markdown(report_data: dict[str, Any]) -> str:
```

to:

```python
def render_report_markdown(
    report_data: dict[str, Any],
    interpretations: dict[str, Any] | None = None,
) -> str:
```

and render with:

```python
        **_markdown_template_context(report_data, interpretations)
```

- [ ] **Step 4: Update both Jinja templates**

In both:
- `skills/drug-target-reporting/templates/drug_report.md.j2`
- `src/agents/drug_target/templates/drug_report.md.j2`

Insert the conditional snippets immediately before each existing `<!-- EXPAND: ... -->` comment.

Use these exact blocks:

```jinja2
{% if interpretations.executive_summary_opportunities | default('') %}
{{ interpretations.executive_summary_opportunities }}

{% endif %}
```

```jinja2
{% if interpretations.scoring_landscape | default('') %}
{{ interpretations.scoring_landscape }}

{% endif %}
```

```jinja2
{% if interpretations.stage1_filter | default('') %}
{{ interpretations.stage1_filter }}

{% endif %}
```

Inside the candidate loop, before the drug-profile `EXPAND`:

```jinja2
{% if card._interpretations.drug_profile | default('') %}
{{ card._interpretations.drug_profile }}

{% endif %}
```

Before biological context `EXPAND`:

```jinja2
{% if card._interpretations.biological_context | default('') %}
{{ card._interpretations.biological_context }}

{% endif %}
```

Before recommendation `EXPAND`:

```jinja2
{% if card._interpretations.recommendation | default('') %}
{{ card._interpretations.recommendation }}

{% endif %}
```

Before hypothesis overview `EXPAND`:

```jinja2
{% if interpretations.hypotheses_overview | default('') %}
{{ interpretations.hypotheses_overview }}

{% endif %}
```

Before each hypothesis implication `EXPAND`:

```jinja2
{% if h._interpretation | default('') %}
{{ h._interpretation }}

{% endif %}
```

Before final recommendations `EXPAND`:

```jinja2
{% if interpretations.final_recommendations | default('') %}
{{ interpretations.final_recommendations }}

{% endif %}
```

- [ ] **Step 5: Run render insertion test**

Run:

```bash
pytest tests/agents/drug_target/test_report_interpretations_mvp4.py::test_render_report_markdown_inserts_accepted_interpretations -q
```

Expected: pass.

- [ ] **Step 6: Verify fallback template byte alignment**

Run:

```bash
cmp -s skills/drug-target-reporting/templates/drug_report.md.j2 src/agents/drug_target/templates/drug_report.md.j2
```

Expected: exit code `0`.

- [ ] **Step 7: Run deterministic MVP regression tests**

Run:

```bash
pytest tests/agents/drug_target/test_deterministic_report_mvp.py -q
```

Expected: pass. Existing one-argument `render_report_markdown(report_data)` calls still work and final markdown contains no `EXPAND`.

- [ ] **Step 8: Commit Task 3**

```bash
git add src/agents/drug_target/deterministic_report.py skills/drug-target-reporting/templates/drug_report.md.j2 src/agents/drug_target/templates/drug_report.md.j2 tests/agents/drug_target/test_report_interpretations_mvp4.py
git commit -m "Render validated interpretation snippets in report template

Constraint: Template fallback and repo-local template must stay byte-aligned.
Rejected: Direct EXPAND replacement in rendered markdown | context-driven rendering is easier to validate.
Confidence: medium
Scope-risk: moderate
Directive: Keep unfilled EXPAND markers stripped so no-LLM output remains clean.
Tested: pytest tests/agents/drug_target/test_report_interpretations_mvp4.py tests/agents/drug_target/test_deterministic_report_mvp.py -q
Not-tested: Browser rendering beyond existing HTML smoke coverage."
```

## Task 4: Integrate Optional Interpretations Into Finalize Path

**Files:**
- Modify: `src/agents/drug_target/deterministic_report.py`
- Modify: `src/agents/drug_target/report_interpretations.py`
- Test: `tests/agents/drug_target/test_report_interpretations_mvp4.py`
- Test: `tests/agents/drug_target/test_finalize_report_mvp3_integration.py`

- [ ] **Step 1: Write failing finalize opt-in tests**

Append:

```python
def test_finalize_report_mvp_does_not_call_interpretation_provider_by_default(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp

    workspace = _copy_baseline_workspace(tmp_path)

    def provider(card):
        raise AssertionError("provider must not be called without opt-in")

    result = asyncio.run(
        finalize_report_mvp(
            {
                "data_dir": str(workspace),
                "disease": "idiopathic pulmonary fibrosis",
                "report_finalization_error": None,
                "evidence_truncated": False,
            },
            {"configurable": {"report_interpretation_provider": provider}},
        )
    )

    assert result["report_finalization_error"] is None
    assert not (workspace / "report_interpretations.json").exists()
    assert "EXPAND" not in (workspace / "drug.md").read_text(encoding="utf-8")


def test_finalize_report_mvp_writes_accepted_interpretations_when_enabled(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp

    workspace = _copy_baseline_workspace(tmp_path)

    def provider(card):
        if card["id"] == "executive_summary.opportunities":
            return "FN1 anchors a deterministic opportunity in the 41-gene assessment."
        return ""

    result = asyncio.run(
        finalize_report_mvp(
            {
                "data_dir": str(workspace),
                "disease": "idiopathic pulmonary fibrosis",
                "report_finalization_error": None,
                "evidence_truncated": False,
            },
            {
                "configurable": {
                    "enable_report_interpretations": True,
                    "report_interpretation_provider": provider,
                }
            },
        )
    )

    assert result["report_finalization_error"] is None
    payload = json.loads((workspace / "report_interpretations.json").read_text(encoding="utf-8"))
    assert payload["summary"]["accepted"] == 1
    assert payload["summary"]["missing"] >= 1
    assert "FN1 anchors a deterministic opportunity" in (workspace / "drug.md").read_text(encoding="utf-8")


def test_finalize_report_mvp_rejects_invalid_interpretation_and_still_succeeds(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp

    workspace = _copy_baseline_workspace(tmp_path)

    def provider(card):
        if card["id"] == "executive_summary.opportunities":
            return "NINTEDANIB improves 99% outcomes through TGFB2 according to fabricated.json."
        return ""

    result = asyncio.run(
        finalize_report_mvp(
            {
                "data_dir": str(workspace),
                "disease": "idiopathic pulmonary fibrosis",
                "report_finalization_error": None,
                "evidence_truncated": False,
            },
            {
                "configurable": {
                    "enable_report_interpretations": True,
                    "report_interpretation_provider": provider,
                }
            },
        )
    )

    assert result["report_finalization_error"] is None
    payload = json.loads((workspace / "report_interpretations.json").read_text(encoding="utf-8"))
    assert payload["summary"]["rejected"] >= 1
    assert "NINTEDANIB improves" not in (workspace / "drug.md").read_text(encoding="utf-8")
    validation = json.loads((workspace / "report_validation.json").read_text(encoding="utf-8"))
    assert validation["valid"] is True
```

- [ ] **Step 2: Run failing finalize opt-in tests**

Run:

```bash
pytest tests/agents/drug_target/test_report_interpretations_mvp4.py::test_finalize_report_mvp_does_not_call_interpretation_provider_by_default tests/agents/drug_target/test_report_interpretations_mvp4.py::test_finalize_report_mvp_writes_accepted_interpretations_when_enabled tests/agents/drug_target/test_report_interpretations_mvp4.py::test_finalize_report_mvp_rejects_invalid_interpretation_and_still_succeeds -q
```

Expected: opt-in tests fail because `finalize_report_mvp` ignores interpretation config.

- [ ] **Step 3: Add provider resolution**

Append to `report_interpretations.py`:

```python
def interpretation_provider_from_config(config: Mapping[str, Any] | None):
    configurable = config.get("configurable", {}) if isinstance(config, Mapping) else {}
    if isinstance(configurable, Mapping):
        provider = configurable.get(INTERPRETATION_PROVIDER_CONFIG_KEY)
        if provider is not None:
            return provider
    return None
```

- [ ] **Step 4: Integrate into `finalize_report_mvp`**

In `deterministic_report.py`, add imports inside `finalize_report_mvp` after report validation passes, not at module top:

```python
    from src.agents.drug_target.report_interpretations import (
        generate_report_interpretations,
        interpretation_provider_from_config,
        report_interpretations_enabled,
    )
```

Before `markdown = render_report_markdown(report_data)`, add:

```python
    interpretations: dict[str, Any] | None = None
    if report_interpretations_enabled(config):
        provider = interpretation_provider_from_config(config)
        if provider is None:
            from src.agents.model import create_llm

            llm = create_llm(os.getenv("LLM_PROVIDER", "openrouter")).bind(temperature=0)

            async def provider(card: dict[str, Any]) -> str:
                prompt = (
                    "Write a concise, evidence-grounded report interpretation snippet. "
                    "Use only the allowed genes, drugs, numbers, and sources in this card. "
                    "Return plain text only.\n\n"
                    f"{json.dumps(card, ensure_ascii=False)}"
                )
                result = llm.invoke(prompt)
                return str(getattr(result, "content", result) or "").strip()

        interpretation_payload, interpretations = await generate_report_interpretations(
            report_data,
            provider=provider,
        )
        _write_json(base / "report_interpretations.json", interpretation_payload)
```

Change:

```python
    markdown = render_report_markdown(report_data)
```

to:

```python
    markdown = render_report_markdown(report_data, interpretations)
```

Keep `config` available by deleting `del config` at the top of `finalize_report_mvp`.

- [ ] **Step 5: Run finalize opt-in tests**

Run:

```bash
pytest tests/agents/drug_target/test_report_interpretations_mvp4.py::test_finalize_report_mvp_does_not_call_interpretation_provider_by_default tests/agents/drug_target/test_report_interpretations_mvp4.py::test_finalize_report_mvp_writes_accepted_interpretations_when_enabled tests/agents/drug_target/test_report_interpretations_mvp4.py::test_finalize_report_mvp_rejects_invalid_interpretation_and_still_succeeds -q
```

Expected: pass.

- [ ] **Step 6: Add production finalize regression for no default interpretations**

Append to `tests/agents/drug_target/test_finalize_report_mvp3_integration.py`:

```python
@pytest.mark.asyncio
async def test_finalize_report_keeps_interpretations_disabled_by_default(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.finalize_report import finalize_report

    workspace = _copy_baseline_workspace(tmp_path)

    result = await finalize_report(_state(workspace), {})

    assert result["report_finalization_error"] is None
    assert not (workspace / "report_interpretations.json").exists()
    assert not (workspace / "report_expansions.json").exists()
```

- [ ] **Step 7: Run MVP3 integration tests**

Run:

```bash
pytest tests/agents/drug_target/test_finalize_report_mvp3_integration.py -q
```

Expected: pass.

- [ ] **Step 8: Commit Task 4**

```bash
git add src/agents/drug_target/deterministic_report.py src/agents/drug_target/report_interpretations.py tests/agents/drug_target/test_report_interpretations_mvp4.py tests/agents/drug_target/test_finalize_report_mvp3_integration.py
git commit -m "Integrate opt-in validated report interpretations

Constraint: Production finalization must remain deterministic unless interpretation enrichment is explicitly enabled.
Rejected: Live provider calls in default tests | would make deterministic finalizer CI credential-dependent.
Confidence: medium
Scope-risk: moderate
Directive: Never fail finalization because optional interpretation snippets fail.
Tested: pytest tests/agents/drug_target/test_report_interpretations_mvp4.py tests/agents/drug_target/test_finalize_report_mvp3_integration.py -q
Not-tested: Live OpenAI/OpenRouter/Ollama provider output quality."
```

## Task 5: Extend MVP4 Harness Diagnostics

**Files:**
- Modify: `src/agents/drug_target/report_harness.py`
- Test: `tests/agents/drug_target/test_report_harness_mvp4.py`

- [ ] **Step 1: Write failing diagnostics success test**

Create `tests/agents/drug_target/test_report_harness_mvp4.py`:

```python
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clear_llm_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "LLM_PROVIDER",
        "DEEPMAST_ENABLE_REPORT_INTERPRETATIONS",
    ):
        monkeypatch.delenv(name, raising=False)


def _copy_baseline_workspace(tmp_path: Path) -> Path:
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "baseline_hallucinated"
    )
    workspace = tmp_path / "workspace"
    shutil.copytree(fixture, workspace)
    return workspace


def test_harness_mvp4_success_checks_are_present(tmp_path: Path) -> None:
    from src.agents.drug_target.report_harness import run_deterministic_report_harness

    workspace = _copy_baseline_workspace(tmp_path)

    result = asyncio.run(
        run_deterministic_report_harness(
            {
                "data_dir": str(workspace),
                "disease": "idiopathic pulmonary fibrosis",
                "report_finalization_error": None,
                "evidence_truncated": False,
            },
            {},
        )
    )

    diagnostics = result["report_harness_diagnostics"]
    checks = diagnostics["checks"]

    assert diagnostics["valid"] is True
    assert checks["no_llm_success"]["status"] == "pass"
    assert checks["artifact_validity"]["status"] == "pass"
    assert checks["source_consistency"]["status"] == "pass"
    assert checks["target_assessment"]["expected"] is False
    assert checks["optional_legacy_artifacts"]["report_expansions.json"]["exists"] is False
    assert checks["optional_legacy_artifacts"]["report_interpretations.json"]["exists"] is False
```

- [ ] **Step 2: Run failing diagnostics success test**

Run:

```bash
pytest tests/agents/drug_target/test_report_harness_mvp4.py::test_harness_mvp4_success_checks_are_present -q
```

Expected: fail with `KeyError: 'checks'`.

- [ ] **Step 3: Add check helpers to `report_harness.py`**

Add imports:

```python
import hashlib
from collections import Counter
from collections.abc import Iterable
```

Add helpers before `collect_report_harness_diagnostics`:

```python
OPTIONAL_LEGACY_ARTIFACTS = (
    "report_expansions.json",
    "drug_report_render.json",
    "report_interpretations.json",
)


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_validity_check(artifacts: dict[str, dict[str, Any]], issues: list[dict[str, Any]]) -> dict[str, Any]:
    blocking_codes = {
        "MISSING_REQUIRED_ARTIFACT",
        "MALFORMED_ARTIFACT_JSON",
        "REPORT_VALIDATION_FAILED",
        "UNEXPANDED_PLACEHOLDER",
    }
    return {
        "status": "fail" if any(issue.get("code") in blocking_codes for issue in issues) else "pass",
        "required_artifacts": artifacts,
    }


def _source_consistency_check(base: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = base / "report_data.json"
    if not path.exists():
        return {"status": "skipped", "sources_checked": 0}, []
    try:
        report_data = _read_json(path)
    except json.JSONDecodeError:
        return {"status": "skipped", "sources_checked": 0}, []
    sources = report_data.get("sources") if isinstance(report_data, dict) else {}
    if not isinstance(sources, dict):
        return {"status": "fail", "sources_checked": 0}, [
            {
                "code": "REPORT_DATA_SOURCES_INVALID",
                "severity": "critical",
                "message": "report_data.json sources must be an object",
                "path": "report_data.json",
            }
        ]

    issues: list[dict[str, Any]] = []
    checked = 0
    for rel_path, metadata in sources.items():
        source_path = base / str(rel_path)
        if not source_path.exists():
            issues.append(
                {
                    "code": "MISSING_DECLARED_SOURCE",
                    "severity": "critical",
                    "message": f"report_data source is missing: {rel_path}",
                    "path": str(rel_path),
                }
            )
            continue
        checked += 1
        expected = metadata.get("sha256") if isinstance(metadata, dict) else None
        actual = _sha256_path(source_path)
        if expected and expected != actual:
            issues.append(
                {
                    "code": "SOURCE_HASH_MISMATCH",
                    "severity": "critical",
                    "message": f"report_data source hash mismatch: {rel_path}",
                    "path": str(rel_path),
                    "expected": expected,
                    "actual": actual,
                }
            )
    return {"status": "fail" if issues else "pass", "sources_checked": checked}, issues


def _target_assessment_check(base: Path) -> dict[str, Any]:
    expected = (base / "lr_candidates.json").exists()
    path = base / "target_assessment.json"
    result: dict[str, Any] = {
        "expected": expected,
        "exists": path.exists(),
        "status": "skipped",
    }
    if not expected:
        return result
    if not path.exists():
        result["status"] = "fail"
        result["errors"] = ["target_assessment.json is required when lr_candidates.json exists"]
        return result
    try:
        from src.agents.drug_target.tools.assessment_output import (
            validate_target_assessment_file,
        )

        validation = validate_target_assessment_file(base)
    except Exception as exc:
        result["status"] = "fail"
        result["errors"] = [f"validator raised: {exc}"]
        return result
    result["status"] = "pass" if validation.get("valid") else "fail"
    result["valid"] = bool(validation.get("valid"))
    result["errors"] = validation.get("errors", [])
    result["matrix_pair_count"] = validation.get("matrix_pair_count")
    return result


def _optional_legacy_artifacts(base: Path) -> dict[str, dict[str, Any]]:
    return {name: _json_metadata(base, name) for name in OPTIONAL_LEGACY_ARTIFACTS}


def _interpretation_check(optional_artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    metadata = optional_artifacts["report_interpretations.json"]
    if not metadata["exists"]:
        return {"status": "absent", "enabled": False}
    if metadata.get("valid_json") is False:
        return {"status": "malformed", "enabled": True}
    return {"status": "present", "enabled": True}


def _no_llm_success_check(finalizer_result: dict[str, Any] | None, diagnostics_valid: bool) -> dict[str, Any]:
    if not finalizer_result:
        return {"status": "skipped"}
    success = (
        diagnostics_valid
        and finalizer_result.get("report_finalization_error") is None
        and finalizer_result.get("evidence_truncated") is False
    )
    return {"status": "pass" if success else "fail"}
```

- [ ] **Step 4: Add checks to diagnostics payload**

In `collect_report_harness_diagnostics`, after `issues = [...]`, add:

```python
    source_check, source_issues = _source_consistency_check(base)
    issues.extend(source_issues)
    optional_artifacts = _optional_legacy_artifacts(base)
    checks = {
        "artifact_validity": _artifact_validity_check(artifacts, issues),
        "source_consistency": source_check,
        "target_assessment": _target_assessment_check(base),
        "optional_legacy_artifacts": optional_artifacts,
        "interpretations": _interpretation_check(optional_artifacts),
    }
```

Return:

```python
        "valid": not issues,
```

and add:

```python
        "checks": checks,
```

In `run_deterministic_report_harness`, after:

```python
    diagnostics["finalizer_result"] = finalizer_result
```

add:

```python
    checks = diagnostics.setdefault("checks", {})
    if isinstance(checks, dict):
        checks["no_llm_success"] = _no_llm_success_check(
            finalizer_result,
            bool(diagnostics.get("valid")),
        )
```

- [ ] **Step 5: Run diagnostics success test**

Run:

```bash
pytest tests/agents/drug_target/test_report_harness_mvp4.py::test_harness_mvp4_success_checks_are_present -q
```

Expected: pass.

- [ ] **Step 6: Write failing source consistency and target assessment tests**

Append:

```python
def test_harness_mvp4_flags_source_hash_mismatch(tmp_path: Path) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp
    from src.agents.drug_target.report_harness import collect_report_harness_diagnostics

    workspace = _copy_baseline_workspace(tmp_path)
    result = asyncio.run(
        finalize_report_mvp(
            {
                "data_dir": str(workspace),
                "disease": "idiopathic pulmonary fibrosis",
                "report_finalization_error": None,
                "evidence_truncated": False,
            },
            {},
        )
    )
    assert result["report_finalization_error"] is None

    assessment_path = workspace / "evidence" / "assessment_results.json"
    payload = json.loads(assessment_path.read_text(encoding="utf-8"))
    payload["synthetic_hash_drift"] = True
    assessment_path.write_text(json.dumps(payload), encoding="utf-8")

    diagnostics = collect_report_harness_diagnostics(str(workspace))

    assert diagnostics["valid"] is False
    assert diagnostics["checks"]["source_consistency"]["status"] == "fail"
    assert any(issue["code"] == "SOURCE_HASH_MISMATCH" for issue in diagnostics["issues"])


def test_harness_mvp4_tracks_valid_target_assessment_when_lr_candidates_exist(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.report_harness import run_deterministic_report_harness

    workspace = _copy_baseline_workspace(tmp_path)
    (workspace / "lr_candidates.json").write_text(
        json.dumps(
            {
                "pairs": [
                    {"ligand": "ICAM1", "receptor": "MUC1"},
                    {"ligand": "FN1", "receptor": "PLAUR"},
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = asyncio.run(
        run_deterministic_report_harness(
            {
                "data_dir": str(workspace),
                "disease": "idiopathic pulmonary fibrosis",
                "report_finalization_error": None,
                "evidence_truncated": False,
            },
            {},
        )
    )

    target_check = result["report_harness_diagnostics"]["checks"]["target_assessment"]
    assert target_check["expected"] is True
    assert target_check["exists"] is True
    assert target_check["status"] == "pass"
    assert target_check["valid"] is True
    assert target_check["matrix_pair_count"] == 2
```

- [ ] **Step 7: Run source/target tests**

Run:

```bash
pytest tests/agents/drug_target/test_report_harness_mvp4.py::test_harness_mvp4_flags_source_hash_mismatch tests/agents/drug_target/test_report_harness_mvp4.py::test_harness_mvp4_tracks_valid_target_assessment_when_lr_candidates_exist -q
```

Expected: pass after helper implementation.

- [ ] **Step 8: Write optional artifact presence test**

Append:

```python
def test_harness_mvp4_tracks_optional_legacy_artifacts_without_deleting(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp
    from src.agents.drug_target.report_harness import collect_report_harness_diagnostics

    workspace = _copy_baseline_workspace(tmp_path)
    result = asyncio.run(
        finalize_report_mvp(
            {
                "data_dir": str(workspace),
                "disease": "idiopathic pulmonary fibrosis",
                "report_finalization_error": None,
                "evidence_truncated": False,
            },
            {},
        )
    )
    assert result["report_finalization_error"] is None

    (workspace / "report_expansions.json").write_text("{}", encoding="utf-8")
    (workspace / "drug_report_render.json").write_text("{}", encoding="utf-8")

    diagnostics = collect_report_harness_diagnostics(str(workspace))
    optional = diagnostics["checks"]["optional_legacy_artifacts"]

    assert optional["report_expansions.json"]["exists"] is True
    assert optional["report_expansions.json"]["valid_json"] is True
    assert optional["drug_report_render.json"]["exists"] is True
    assert (workspace / "report_expansions.json").exists()
    assert (workspace / "drug_report_render.json").exists()
```

- [ ] **Step 9: Run optional artifact test**

Run:

```bash
pytest tests/agents/drug_target/test_report_harness_mvp4.py::test_harness_mvp4_tracks_optional_legacy_artifacts_without_deleting -q
```

Expected: pass.

- [ ] **Step 10: Commit Task 5**

```bash
git add src/agents/drug_target/report_harness.py tests/agents/drug_target/test_report_harness_mvp4.py
git commit -m "Track MVP4 deterministic report harness checks

Constraint: Harness diagnostics must stay provider-free and must not mutate legacy artifacts.
Rejected: Making optional artifacts required | deterministic MVP path intentionally avoids report_expansions.json.
Confidence: medium
Scope-risk: moderate
Directive: Add future eval checks under diagnostics.checks without breaking MVP2 top-level fields.
Tested: pytest tests/agents/drug_target/test_report_harness_mvp4.py -q
Not-tested: Large live result directory sweeps."
```

## Task 6: Add Diagnostics Aggregation And Holdout Trace Hook

**Files:**
- Modify: `src/agents/drug_target/report_harness.py`
- Test: `tests/agents/drug_target/test_report_harness_mvp4.py`

- [ ] **Step 1: Write failing aggregation test**

Append:

```python
def test_aggregate_report_harness_diagnostics_counts_validity_and_issues() -> None:
    from src.agents.drug_target.report_harness import aggregate_report_harness_diagnostics

    aggregate = aggregate_report_harness_diagnostics(
        [
            {
                "valid": True,
                "issues": [],
                "checks": {
                    "source_consistency": {"status": "pass"},
                    "target_assessment": {"status": "skipped"},
                },
            },
            {
                "valid": False,
                "issues": [
                    {"code": "SOURCE_HASH_MISMATCH"},
                    {"code": "MISSING_REQUIRED_ARTIFACT"},
                ],
                "checks": {
                    "source_consistency": {"status": "fail"},
                    "target_assessment": {"status": "fail"},
                },
            },
        ]
    )

    assert aggregate == {
        "schema_version": "drug_target.report_harness_eval.v1",
        "total": 2,
        "valid": 1,
        "invalid": 1,
        "issue_code_counts": {
            "MISSING_REQUIRED_ARTIFACT": 1,
            "SOURCE_HASH_MISMATCH": 1,
        },
        "check_status_counts": {
            "source_consistency": {"fail": 1, "pass": 1},
            "target_assessment": {"fail": 1, "skipped": 1},
        },
    }
```

- [ ] **Step 2: Run failing aggregation test**

Run:

```bash
pytest tests/agents/drug_target/test_report_harness_mvp4.py::test_aggregate_report_harness_diagnostics_counts_validity_and_issues -q
```

Expected: fail because `aggregate_report_harness_diagnostics` is missing.

- [ ] **Step 3: Implement aggregation**

Append to `report_harness.py`:

```python
def aggregate_report_harness_diagnostics(
    diagnostics: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    total = 0
    valid_count = 0
    issue_counts: Counter[str] = Counter()
    check_status_counts: dict[str, Counter[str]] = {}

    for payload in diagnostics:
        total += 1
        if payload.get("valid") is True:
            valid_count += 1
        for issue in payload.get("issues", []):
            if isinstance(issue, dict) and issue.get("code"):
                issue_counts[str(issue["code"])] += 1
        checks = payload.get("checks", {})
        if isinstance(checks, dict):
            for name, check in checks.items():
                if not isinstance(check, dict):
                    continue
                status = str(check.get("status") or "unknown")
                check_status_counts.setdefault(str(name), Counter())[status] += 1

    return {
        "schema_version": "drug_target.report_harness_eval.v1",
        "total": total,
        "valid": valid_count,
        "invalid": total - valid_count,
        "issue_code_counts": dict(sorted(issue_counts.items())),
        "check_status_counts": {
            name: dict(sorted(counter.items()))
            for name, counter in sorted(check_status_counts.items())
        },
    }
```

- [ ] **Step 4: Run aggregation test**

Run:

```bash
pytest tests/agents/drug_target/test_report_harness_mvp4.py::test_aggregate_report_harness_diagnostics_counts_validity_and_issues -q
```

Expected: pass.

- [ ] **Step 5: Write holdout trace availability test**

Append:

```python
def test_holdout_trace_fixture_remains_analyzable_when_available() -> None:
    from scripts.analyze_drug_target_trace_variability import analyze_trace_file

    trace_path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "v8_run_excerpt"
        / "v8_partial_run.jsonl"
    )
    if not trace_path.exists():
        pytest.skip("No holdout trace fixture available")

    stats = analyze_trace_file(trace_path)

    assert stats["trace_path"] == str(trace_path)
    assert "issue_codes" in stats
    assert "final_pass" in stats
```

- [ ] **Step 6: Run holdout trace test**

Run:

```bash
pytest tests/agents/drug_target/test_report_harness_mvp4.py::test_holdout_trace_fixture_remains_analyzable_when_available -q
```

Expected: pass if fixture exists, skip otherwise. Do not assert `final_pass is True` because the current fixture is a partial trace excerpt.

- [ ] **Step 7: Commit Task 6**

```bash
git add src/agents/drug_target/report_harness.py tests/agents/drug_target/test_report_harness_mvp4.py
git commit -m "Aggregate deterministic report harness diagnostics

Constraint: Holdout trace checks are included only when repo fixtures exist.
Rejected: Requiring partial trace final_pass=true | current v8 fixture is not a complete success trace.
Confidence: high
Scope-risk: narrow
Directive: Keep aggregation pure and side-effect-free for fixture eval loops.
Tested: pytest tests/agents/drug_target/test_report_harness_mvp4.py -q
Not-tested: Multi-directory live eval sweeps."
```

## Task 7: Final Verification And Routing Guard

**Files:**
- Verify only

- [ ] **Step 1: Run focused MVP4 tests**

Run:

```bash
pytest tests/agents/drug_target/test_report_interpretations_mvp4.py tests/agents/drug_target/test_report_harness_mvp4.py -q
```

Expected: pass.

- [ ] **Step 2: Run prior deterministic/harness/integration regressions**

Run:

```bash
pytest tests/agents/drug_target/test_deterministic_report_mvp.py tests/agents/drug_target/test_report_harness_mvp2.py tests/agents/drug_target/test_finalize_report_mvp3_integration.py tests/agents/drug_target/test_super_graph_topology.py tests/scripts/test_analyze_drug_target_trace_variability.py -q
```

Expected: pass.

- [ ] **Step 3: Verify production routing files are unchanged unless intentionally edited**

Run:

```bash
git diff --exit-code origin/main...HEAD -- src/agents/drug_target/super_graph.py src/agents/drug_target/agent.py
```

Expected: no output. `finalize_report.py` may remain unchanged; if changed, inspect manually and confirm `finalize_report` still delegates to `finalize_report_mvp`.

- [ ] **Step 4: Verify no original `res_ipf_*` directory was mutated**

Run:

```bash
git status --short -- res_ipf_openai_tmp res_ipf_ollama_tmp
```

Expected: no output.

- [ ] **Step 5: Verify default path does not create interpretation or legacy expansion artifacts**

Run:

```bash
tmp_base=$(mktemp -d /tmp/deepmast_mvp4_verify.XXXXXX)
cp -R tests/agents/drug_target/fixtures/baseline_hallucinated "$tmp_base/workspace"
PYTHONPATH=. LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false python - <<'PY' "$tmp_base/workspace"
import asyncio
import json
import sys
from pathlib import Path
from src.agents.drug_target.finalize_report import finalize_report

workspace = Path(sys.argv[1])

async def main():
    result = await finalize_report(
        {
            "data_dir": str(workspace),
            "disease": "idiopathic pulmonary fibrosis",
            "messages": [],
            "featured_lr_pairs": None,
            "report_finalization_error": None,
            "evidence_truncated": False,
        },
        {},
    )
    validation = json.loads((workspace / "report_validation.json").read_text())
    print(json.dumps({
        "result": result,
        "validation_valid": validation.get("valid"),
        "has_report_expansions": (workspace / "report_expansions.json").exists(),
        "has_report_interpretations": (workspace / "report_interpretations.json").exists(),
        "has_expand": "EXPAND" in (workspace / "drug.md").read_text(),
    }, indent=2))

asyncio.run(main())
PY
```

Expected JSON:

```json
{
  "result": {
    "report_finalization_error": null,
    "evidence_truncated": false
  },
  "validation_valid": true,
  "has_report_expansions": false,
  "has_report_interpretations": false,
  "has_expand": false
}
```

- [ ] **Step 6: Verify opt-in mock enrichment smoke**

Run:

```bash
tmp_base=$(mktemp -d /tmp/deepmast_mvp4_interpret.XXXXXX)
cp -R tests/agents/drug_target/fixtures/baseline_hallucinated "$tmp_base/workspace"
PYTHONPATH=. LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false python - <<'PY' "$tmp_base/workspace"
import asyncio
import json
import sys
from pathlib import Path
from src.agents.drug_target.deterministic_report import finalize_report_mvp

workspace = Path(sys.argv[1])

def provider(card):
    if card["id"] == "executive_summary.opportunities":
        return "FN1 anchors a deterministic opportunity in the 41-gene assessment."
    return ""

async def main():
    result = await finalize_report_mvp(
        {
            "data_dir": str(workspace),
            "disease": "idiopathic pulmonary fibrosis",
            "report_finalization_error": None,
            "evidence_truncated": False,
        },
        {
            "configurable": {
                "enable_report_interpretations": True,
                "report_interpretation_provider": provider,
            }
        },
    )
    payload = json.loads((workspace / "report_interpretations.json").read_text())
    print(json.dumps({
        "result": result,
        "accepted": payload["summary"]["accepted"],
        "contains_snippet": "FN1 anchors a deterministic opportunity" in (workspace / "drug.md").read_text(),
    }, indent=2))

asyncio.run(main())
PY
```

Expected JSON:

```json
{
  "result": {
    "report_finalization_error": null,
    "evidence_truncated": false
  },
  "accepted": 1,
  "contains_snippet": true
}
```

- [ ] **Step 7: Commit verification-only docs if needed**

If the plan document itself is committed separately, use:

```bash
git add docs/superpowers/plans/2026-05-23-deterministic-report-mvp4-validated-interpretations.md
git commit -m "Plan validated interpretation harness work

Constraint: MVP4 scope changed before implementation to include opt-in interpretation snippets.
Rejected: Separate immediate PR for interpretation planning | no implementation had started yet, so a single coherent MVP4 plan is cheaper.
Confidence: high
Scope-risk: narrow
Directive: Follow this plan TDD; do not add live provider tests to the default suite.
Tested: Plan self-review only.
Not-tested: Implementation not started."
```

## Self-Review

Spec coverage:
- Harness/eval diagnostics: Tasks 5 and 6.
- Artifact validity, no-LLM success, source consistency, `target_assessment`, optional/legacy artifact presence: Task 5.
- Optional validated LLM snippets: Tasks 1 through 4.
- Provider-free default tests: Tasks 4 and 7.
- No production routing change: Task 7.
- Holdout trace only if available: Task 6.

Placeholder scan:
- This plan contains no unresolved placeholder markers or incomplete implementation steps.
- Tests include exact assertions and commands.
- Code snippets define the referenced functions before later tasks use them.

Type consistency:
- Config keys are consistently `enable_report_interpretations` and `report_interpretation_provider`.
- Output schema versions are consistently `drug_target.report_interpretations.v1` and `drug_target.report_harness_eval.v1`.
- Render map keys match template insertion keys.

## Addendum: Style-Diverse Validated Snippets

Optional LLM interpretation snippets now carry card-specific prose roles so
`drug_profile`, `biological_context`, `recommendation`, and `hypothesis`
expansion slots do not all ask for the same generic interpretation. The
validator remains claim-first: genes, drugs, sources, numbers, and report terms
must still be present in the card allowlists.

Report terms such as `Stage 1`, `Stage 3`, `validated track`, and
`exploratory track` are card-scoped `allowed_terms`, not global exceptions.
This preserves deterministic fallback behavior while allowing richer language
when the deterministic card explicitly supplies the term.

When a provider returns invalid text, `generate_report_interpretations` retries
once with a repair card containing the previous text and validator issues. If
the retry remains invalid, the snippet is rejected and the deterministic
fallback remains in the rendered report.

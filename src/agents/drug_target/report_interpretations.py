"""Optional validated interpretation snippets for deterministic drug reports."""

from __future__ import annotations

import inspect
import json
import os
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any


INTERPRETATIONS_SCHEMA_VERSION = "drug_target.report_interpretations.v1"
ENABLE_INTERPRETATIONS_ENV = "DEEPMAST_ENABLE_REPORT_INTERPRETATIONS"
ENABLE_INTERPRETATIONS_CONFIG_KEY = "enable_report_interpretations"
INTERPRETATION_PROVIDER_CONFIG_KEY = "report_interpretation_provider"

_ENTITY_TOKEN_RE = re.compile(
    r"\b(?:[A-Z][A-Z0-9-]{2,}|[A-Z][a-z]+[0-9]+|[A-Z][A-Za-z0-9-]{3,}ib)\b"
)
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def report_interpretations_enabled(config: Mapping[str, Any] | None) -> bool:
    configurable = config.get("configurable") if config else None
    if (
        isinstance(configurable, Mapping)
        and configurable.get(ENABLE_INTERPRETATIONS_CONFIG_KEY) is True
    ):
        return True

    env_value = os.environ.get(ENABLE_INTERPRETATIONS_ENV, "")
    return env_value.strip().lower() in {"1", "true", "yes", "on"}


def _provider_creation_error_provider(exc: Exception) -> Callable[[Mapping[str, Any]], object]:
    def provider(card: Mapping[str, Any]) -> object:
        raise RuntimeError(f"interpretation provider unavailable: {exc}") from exc

    return provider


def _message_content_to_text(response: object) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return "" if content is None else str(content)


def _live_llm_interpretation_provider(llm: object) -> Callable[[Mapping[str, Any]], object]:
    async def provider(card: Mapping[str, Any]) -> object:
        from langchain_core.messages import HumanMessage

        prompt = (
            "Write only the requested deterministic drug-target report "
            "interpretation. Use only the facts and allowed values in this "
            "card. Do not add unsupported genes, drugs, sources, or numbers.\n\n"
            f"{json.dumps(card, sort_keys=True, ensure_ascii=False)}"
        )
        messages = [HumanMessage(content=prompt)]
        if hasattr(llm, "ainvoke"):
            response = await llm.ainvoke(messages)
        elif hasattr(llm, "invoke"):
            response = llm.invoke(messages)
        else:
            raise TypeError("interpretation LLM provider has no invoke method")
        return _message_content_to_text(response)

    return provider


def interpretation_provider_from_config(
    config: Mapping[str, Any] | None,
) -> Callable[[Mapping[str, Any]], object] | None:
    configurable = config.get("configurable") if config else None
    if isinstance(configurable, Mapping):
        provider = configurable.get(INTERPRETATION_PROVIDER_CONFIG_KEY)
        if provider is not None:
            return provider

    if not report_interpretations_enabled(config):
        return None

    try:
        from src.agents.model import create_llm_from_config

        llm = create_llm_from_config(config)
    except Exception as exc:  # noqa: BLE001
        return _provider_creation_error_provider(exc)

    return _live_llm_interpretation_provider(llm)


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


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


def _featured_candidates(
    report_data: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidates = _dict_list(report_data.get("candidates"))
    featured = [
        candidate
        for candidate in candidates
        if candidate.get("stage3_candidate")
    ]
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


def _section_sources(
    report_data: Mapping[str, Any],
    section_id: str,
) -> list[str]:
    sections = report_data.get("sections")
    if not isinstance(sections, dict):
        return []
    section = sections.get(section_id)
    if not isinstance(section, dict):
        return []
    return _string_list(section.get("sources"))


def build_interpretation_cards(
    report_data: Mapping[str, Any],
) -> list[dict[str, Any]]:
    disease = str(report_data.get("disease") or "").strip()
    all_genes = _candidate_genes(report_data)
    featured = _featured_candidates(report_data)
    featured_genes = [
        str(candidate.get("gene") or "").strip().upper()
        for candidate in featured
    ]
    featured_genes = [gene for gene in featured_genes if gene]
    candidates = _dict_list(report_data.get("candidates"))
    hypotheses = _dict_list(report_data.get("hypotheses"))

    cards: list[dict[str, Any]] = [
        {
            "id": "executive_summary.opportunities",
            "kind": "section",
            "instruction": (
                "Write 1-3 sentences summarizing key therapeutic opportunities."
            ),
            "allowed_genes": featured_genes,
            "allowed_drugs": [],
            "allowed_numbers": [str(len(candidates)), str(len(featured_genes))],
            "allowed_sources": _section_sources(report_data, "executive_summary"),
            "facts": {
                "disease": disease,
                "featured_genes": featured_genes,
            },
        },
        {
            "id": "scoring_landscape",
            "kind": "section",
            "instruction": (
                "Write 1-3 sentences interpreting the scoring landscape."
            ),
            "allowed_genes": all_genes,
            "allowed_drugs": [],
            "allowed_numbers": [str(len(candidates)), str(len(featured_genes))],
            "allowed_sources": _section_sources(
                report_data,
                "druggability_matrix",
            ),
            "facts": {"disease": disease},
        },
        {
            "id": "stage1_filter.interpretation",
            "kind": "section",
            "instruction": (
                "Write 1-3 sentences interpreting Stage 1 biological validation."
            ),
            "allowed_genes": all_genes,
            "allowed_drugs": [],
            "allowed_numbers": [],
            "allowed_sources": [
                "evidence/stage1_filter_results.json",
                "evidence/stage1_evidence.json",
            ],
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
                {
                    "id": f"candidate.{gene}.drug_profile",
                    "kind": "candidate",
                    "instruction": "Describe known drugs and indications only.",
                    **base,
                },
                {
                    "id": f"candidate.{gene}.biological_context",
                    "kind": "candidate",
                    "instruction": "Interpret Stage 1 biological context.",
                    **base,
                },
                {
                    "id": f"candidate.{gene}.recommendation",
                    "kind": "candidate",
                    "instruction": (
                        "Write a short evidence-grounded therapeutic "
                        "recommendation."
                    ),
                    **base,
                },
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
            "facts": {
                "disease": disease,
                "hypothesis_count": len(hypotheses),
            },
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
                "instruction": (
                    "Write 1-2 sentences on therapeutic implications of this "
                    "hypothesis."
                ),
                "allowed_genes": _string_list(entities.get("genes")),
                "allowed_drugs": _string_list(entities.get("drugs")),
                "allowed_numbers": [rank] if rank else [],
                "allowed_sources": _string_list(
                    hypothesis.get("evidence_references")
                ),
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
            "instruction": (
                "Write 1-3 sentences recommending next deterministic "
                "follow-up steps."
            ),
            "allowed_genes": featured_genes,
            "allowed_drugs": [],
            "allowed_numbers": [str(len(candidates)), str(len(featured_genes))],
            "allowed_sources": _section_sources(
                report_data,
                "candidate_deep_dives",
            ),
            "facts": {
                "disease": disease,
                "featured_genes": featured_genes,
            },
        }
    )
    return cards


def _allowed_upper_values(values: object) -> set[str]:
    return {value.upper() for value in _string_list(values)}


def _allowed_source_basenames(values: object) -> set[str]:
    return {value.rsplit("/", 1)[-1] for value in _string_list(values)}


def _mask_allowed_spans(text: str, values: object) -> str:
    masked = text
    for value in sorted(_string_list(values), key=len, reverse=True):
        pattern = re.compile(rf"(?<!\w){re.escape(value)}(?!\w)")
        masked = pattern.sub(lambda match: " " * len(match.group(0)), masked)
    return masked


def validate_interpretation_text(
    card: Mapping[str, Any],
    text: str,
) -> list[dict[str, Any]]:
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
                "message": (
                    "Interpretation text contains template placeholder syntax."
                ),
                "card_id": card.get("id"),
            }
        )

    masked = stripped
    for key in ("allowed_genes", "allowed_drugs", "allowed_sources"):
        masked = _mask_allowed_spans(masked, card.get(key))

    allowed_entities = _DOMAIN_TOKEN_ALLOWLIST
    for token in sorted(set(_ENTITY_TOKEN_RE.findall(masked))):
        upper_token = token.upper()
        if upper_token.startswith("CHEMBL"):
            continue
        if upper_token not in allowed_entities:
            issues.append(
                {
                    "code": "UNSUPPORTED_ENTITY",
                    "severity": "critical",
                    "message": (
                        "Unsupported entity token in interpretation: "
                        f"{token}"
                    ),
                    "card_id": card.get("id"),
                    "token": token,
                }
            )

    allowed_sources = set(_string_list(card.get("allowed_sources")))
    allowed_basenames = _allowed_source_basenames(card.get("allowed_sources"))
    for source in sorted(set(_SOURCE_RE.findall(masked))):
        if source not in allowed_sources and source not in allowed_basenames:
            issues.append(
                {
                    "code": "UNSUPPORTED_SOURCE",
                    "severity": "critical",
                    "message": (
                        "Unsupported source reference in interpretation: "
                        f"{source}"
                    ),
                    "card_id": card.get("id"),
                    "source": source,
                }
            )

    allowed_numbers = set(
        str(value) for value in _string_list(card.get("allowed_numbers"))
    )
    for number in sorted(set(_NUMBER_RE.findall(masked))):
        if number not in allowed_numbers:
            issues.append(
                {
                    "code": "UNSUPPORTED_NUMBER",
                    "severity": "critical",
                    "message": (
                        "Unsupported numeric claim in interpretation: "
                        f"{number}"
                    ),
                    "card_id": card.get("id"),
                    "number": number,
                }
            )

    return issues


def _render_key(card_id: str) -> tuple[str, str | None, str | None]:
    if card_id == "executive_summary.opportunities":
        return ("executive_summary_opportunities", None, None)
    if card_id == "scoring_landscape":
        return ("scoring_landscape", None, None)
    if card_id == "stage1_filter.interpretation":
        return ("stage1_filter", None, None)
    if card_id == "hypotheses.overview":
        return ("hypotheses_overview", None, None)
    if card_id == "final_recommendations":
        return ("final_recommendations", None, None)

    parts = card_id.split(".")
    if len(parts) == 3 and parts[0] == "candidate":
        return ("candidates", parts[1], parts[2])
    if len(parts) == 3 and parts[0] == "hypothesis":
        return ("hypotheses", parts[1], parts[2])
    return (card_id.replace(".", "_"), None, None)


def _put_render_text(
    render_map: dict[str, Any],
    card_id: str,
    text: str,
) -> None:
    root_key, nested_key, leaf_key = _render_key(card_id)
    if nested_key is None or leaf_key is None:
        render_map[root_key] = text
        return

    nested = render_map.setdefault(root_key, {})
    if not isinstance(nested, dict):
        nested = {}
        render_map[root_key] = nested
    leaf = nested.setdefault(nested_key, {})
    if not isinstance(leaf, dict):
        leaf = {}
        nested[nested_key] = leaf
    leaf[leaf_key] = text


async def _call_provider(
    provider: Callable[[Mapping[str, Any]], object],
    card: Mapping[str, Any],
) -> str:
    result = provider(card)
    if inspect.isawaitable(result):
        result = await result
    if result is None:
        return ""
    return str(result)


async def generate_report_interpretations(
    report_data: Mapping[str, Any],
    provider: Callable[[Mapping[str, Any]], object],
) -> tuple[dict[str, Any], dict[str, Any]]:
    cards = build_interpretation_cards(report_data)
    summary = {
        "cards": len(cards),
        "accepted": 0,
        "rejected": 0,
        "missing": 0,
        "provider_errors": 0,
    }
    snippets: dict[str, Any] = {}
    render_map: dict[str, Any] = {}

    for card in cards:
        card_id = str(card.get("id") or "")

        try:
            text = (await _call_provider(provider, card)).strip()
        except Exception as exc:  # noqa: BLE001
            summary["provider_errors"] += 1
            snippets[card_id] = {
                "card_id": card_id,
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
            snippets[card_id] = {
                "card_id": card_id,
                "status": "missing",
                "text": "",
                "issues": [],
            }
            continue

        issues = validate_interpretation_text(card, text)
        if issues:
            summary["rejected"] += 1
            snippets[card_id] = {
                "card_id": card_id,
                "status": "rejected",
                "text": text,
                "issues": issues,
            }
            continue

        summary["accepted"] += 1
        _put_render_text(render_map, card_id, text)
        snippets[card_id] = {
            "card_id": card_id,
            "status": "accepted",
            "text": text,
            "issues": [],
        }

    payload = {
        "schema_version": INTERPRETATIONS_SCHEMA_VERSION,
        "enabled": True,
        "created_at": _utc_now(),
        "summary": summary,
        "snippets": snippets,
    }
    return payload, render_map

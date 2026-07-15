from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from scripts import validate_report as validate_report_script
from src.agents.deep_interpreter.tools.literature_rag import (
    search_literature_fulltext as _search_literature_fulltext,
)
from src.agents.model import create_llm


REFERENCE_BLOCK_RE = re.compile(
    r"^### References\s*$\n?(.*?)(?=^### |\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
MARKDOWN_TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
EXPLICIT_HYPOTHESIS_RE = re.compile(
    r"\b(hypothesis|hypothesized|needs validation|requiring validation|novel finding)\b",
    re.IGNORECASE,
)


class ClaimJudgment(BaseModel):
    claim_index: int = Field(ge=0)
    status: Literal["supported", "overclaimed", "unsupported", "unverifiable"]
    reason: str
    supporting_pmids: list[str] = Field(default_factory=list)
    evidence_quote: str = ""


class ClaimJudgmentBatch(BaseModel):
    judgments: list[ClaimJudgment]


class _SearchLiteratureFulltext:
    def invoke(self, args: dict[str, Any]) -> Any:
        return _search_literature_fulltext.invoke(args)


search_literature_fulltext = _SearchLiteratureFulltext()


def _paper_map(data_dir: Path) -> dict[str, dict[str, Any]]:
    data = json.loads((data_dir / "papers.json").read_text(encoding="utf-8"))
    rows = data.get("papers") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return {}
    return {
        str(row["pmid"]): row
        for row in rows
        if isinstance(row, dict) and row.get("pmid")
    }


def _clean_claims(text: str) -> list[str]:
    claims: list[str] = []
    for window in validate_report_script._claim_windows(text):
        claim = re.sub(r"^[-*]\s+", "", window).strip()
        if (
            not claim
            or claim.startswith("#")
            or MARKDOWN_TABLE_RE.match(claim)
            or len(claim.split()) < 4
        ):
            continue
        claims.append(claim)
    return claims


def _reference_pmids(section_body: str) -> list[str]:
    match = REFERENCE_BLOCK_RE.search(section_body)
    if match is None:
        return []
    return sorted(set(validate_report_script.PMID_RE.findall(match.group(1))))


def _claim_items(
    claims: list[str],
    fallback_pmids: list[str],
    known_pmids: set[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, claim in enumerate(claims):
        if EXPLICIT_HYPOTHESIS_RE.search(claim):
            continue
        inline_pmids = sorted(set(validate_report_script.PMID_RE.findall(claim)))
        following = claims[index + 1] if index + 1 < len(claims) else ""
        candidate_pmids = [
            pmid for pmid in (inline_pmids or fallback_pmids) if pmid in known_pmids
        ]
        items.append(
            {
                "index": index,
                "claim": claim,
                "candidate_pmids": candidate_pmids,
                "hedged": bool(
                    validate_report_script.MECHANISTIC_HEDGE_RE.search(claim)
                    or EXPLICIT_HYPOTHESIS_RE.search(following)
                ),
            }
        )
    return items


def _extract_claim_groups(
    data_dir: Path, filenames: tuple[str, ...]
) -> list[dict[str, Any]]:
    data_dir = data_dir.resolve()
    papers = _paper_map(data_dir)
    paper_pmids = sorted(papers)
    groups: list[dict[str, Any]] = []

    for filename in filenames:
        path = data_dir / filename
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for section in validate_report_script._sections(text):
            section_body = str(section["body"])
            if filename == "synthesis.md":
                claims = _clean_claims(section_body)
                fallback_pmids = paper_pmids
            else:
                blocks = validate_report_script._biological_interpretation_blocks(
                    section_body
                )
                claims = [claim for block in blocks for claim in _clean_claims(block)]
                fallback_pmids = _reference_pmids(section_body)
            claim_items = _claim_items(claims, fallback_pmids, set(paper_pmids))
            if claim_items:
                groups.append(
                    {
                        "file": filename,
                        "section": str(section["heading"]),
                        "claims": claim_items,
                    }
                )
    return groups


def _result_pmid(result: dict[str, Any]) -> str | None:
    metadata = result.get("metadata") or {}
    direct = metadata.get("pmid")
    if direct:
        return str(direct)
    source = " ".join(
        str(metadata.get(key) or "") for key in ("filename", "source", "file_path")
    )
    match = re.search(r"pmid[_:\s-]?(\d{6,9})", source, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _abstract_evidence(
    claim: str,
    candidate_pmids: Sequence[str],
    papers: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    claim_tokens = set(re.findall(r"[a-z][a-z0-9-]{2,}", claim.lower()))
    ranked: list[tuple[int, str, str]] = []
    for pmid in candidate_pmids:
        abstract = str(papers.get(pmid, {}).get("abstract") or "").strip()
        if not abstract:
            continue
        abstract_tokens = set(re.findall(r"[a-z][a-z0-9-]{2,}", abstract.lower()))
        ranked.append((len(claim_tokens & abstract_tokens), pmid, abstract))
    ranked.sort(reverse=True)
    return [
        {"pmid": pmid, "source": "abstract", "text": abstract[:1200]}
        for score, pmid, abstract in ranked[:3]
        if score > 0 or len(candidate_pmids) == 1
    ]


def _retrieve_evidence(
    claim: str,
    candidate_pmids: Sequence[str],
    data_dir: Path,
) -> list[dict[str, str]]:
    allowed = set(candidate_pmids)
    if not allowed:
        return []
    try:
        results = search_literature_fulltext.invoke(
            {
                "query": claim,
                "part_name": "all",
                "limit": 15,
                "data_dir": str(data_dir),
            }
        )
    except Exception:
        return []
    evidence: list[dict[str, str]] = []
    for result in results:
        pmid = _result_pmid(result)
        text = str(result.get("page_content") or "").strip()
        if pmid in allowed and text:
            evidence.append({"pmid": pmid, "source": "full_text", "text": text[:1200]})
        if len(evidence) == 3:
            break
    return evidence or _abstract_evidence(claim, candidate_pmids, _paper_map(data_dir))


def _judgment_prompt(group: dict[str, Any]) -> str:
    payload = [
        {
            "claim_index": item["index"],
            "claim": item["claim"],
            "candidate_pmids": item["candidate_pmids"],
            "evidence": item["evidence"],
        }
        for item in group["claims"]
    ]
    return f"""Judge each biological claim using only its supplied evidence.

Statuses:
- supported: evidence directly supports the same subject, relation, direction, disease, and cell context.
- overclaimed: evidence supports a weaker association but the claim adds causality, mechanism, direction, therapeutic effect, or unsupported context.
- unsupported: supplied evidence directly conflicts with the claim or supports a materially different relation.
- unverifiable: evidence is absent, ambiguous, or insufficient. Absence of a statement is not contradiction.

Do not use outside knowledge. Retrieval similarity is not support. Return exactly one judgment for every claim_index. Keep evidence_quote short and copied from supplied evidence.

Claims and evidence:
{json.dumps(payload, indent=2, ensure_ascii=False)}
"""


def _unverifiable(item: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        **item,
        "status": "unverifiable",
        "reason": reason,
        "supporting_pmids": [],
        "evidence_quote": "",
    }


def _judge_group(group: dict[str, Any], model: Any) -> list[dict[str, Any]]:
    evidence_items = [item for item in group["claims"] if item["evidence"]]
    missing = {
        item["index"]: _unverifiable(item, "No allowed PMID evidence was retrieved.")
        for item in group["claims"]
        if not item["evidence"]
    }
    if not evidence_items:
        return [missing[item["index"]] for item in group["claims"]]

    judged_group = {**group, "claims": evidence_items}
    try:
        response = model.with_structured_output(ClaimJudgmentBatch).invoke(
            [HumanMessage(content=_judgment_prompt(judged_group))]
        )
        judgments = {item.claim_index: item for item in response.judgments}
    except Exception as exc:
        return [
            _unverifiable(item, f"Claim judge failed: {type(exc).__name__}.")
            for item in group["claims"]
        ]

    results: list[dict[str, Any]] = []
    for item in group["claims"]:
        if item["index"] in missing:
            results.append(missing[item["index"]])
            continue
        judgment = judgments.get(item["index"])
        if judgment is None:
            results.append(_unverifiable(item, "Claim judge omitted this claim."))
            continue
        results.append(
            {
                **item,
                "status": judgment.status,
                "reason": judgment.reason,
                "supporting_pmids": judgment.supporting_pmids,
                "evidence_quote": judgment.evidence_quote,
            }
        )
    return results


def _issue_for(result: dict[str, Any]) -> dict[str, str] | None:
    status = str(result["status"])
    if status == "supported":
        return None
    hedged = bool(result["hedged"])
    severity = "warning" if status == "unverifiable" or hedged else "error"
    code = "claim_rag_hypothesis_warning" if hedged else f"claim_rag_{status}"
    pmids = ", ".join(result["supporting_pmids"]) or "none"
    quote = str(result["evidence_quote"]).strip()
    evidence = f"{result['reason']} PMIDs: {pmids}."
    if quote:
        evidence += f" Evidence: {quote}"
    instruction = (
        "Leave this claim unchanged and record the evidence gap."
        if severity == "warning"
        else "Rewrite only this claim to match the supported association; do not add a new PMID."
        if status == "overclaimed"
        else "Remove the unsupported assertion or mark it as a hypothesis requiring validation; do not add a new PMID."
    )
    return {
        "code": code,
        "severity": severity,
        "file": str(result["file"]),
        "section": str(result["section"]),
        "value": str(result["claim"]),
        "evidence": evidence,
        "repair_instruction": instruction,
    }


def validate_claims(
    data_dir: str | Path,
    filenames: tuple[str, ...],
    *,
    provider: str | None = None,
    llm: Any | None = None,
    cache: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    data_dir = Path(data_dir).expanduser().resolve()
    cache = cache if cache is not None else {}
    model = llm
    results: list[dict[str, Any]] = []

    for group in _extract_claim_groups(data_dir, filenames):
        cache_key = json.dumps(group, sort_keys=True, ensure_ascii=False)
        cached = cache.get(cache_key)
        if cached is not None:
            results.extend(cached)
            continue
        enriched = {
            **group,
            "claims": [
                {
                    **item,
                    "file": group["file"],
                    "section": group["section"],
                    "evidence": _retrieve_evidence(
                        item["claim"], item["candidate_pmids"], data_dir
                    ),
                }
                for item in group["claims"]
            ],
        }
        if model is None and any(item["evidence"] for item in enriched["claims"]):
            model = create_llm(provider)
        judged = _judge_group(enriched, model)
        cache[cache_key] = judged
        results.extend(judged)

    issues = [issue for result in results if (issue := _issue_for(result)) is not None]
    return {"claims": results, "issues": issues}

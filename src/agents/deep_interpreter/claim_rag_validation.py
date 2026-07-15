from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from scripts import validate_report as validate_report_script


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
                fallback_pmids = _reference_pmids(section_body) or paper_pmids
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

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SECTION_RE = re.compile(r"(^## .+?$)(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)


def _content(message: Any) -> str:
    return str(getattr(message, "content", message))


def _load_issues(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        issues = data
    elif isinstance(data, dict):
        issues = data.get("issues", [])
    else:
        issues = []
    return [i for i in issues if isinstance(i, dict)]


def _find_section(text: str, heading: str) -> tuple[int, int, str] | None:
    for match in SECTION_RE.finditer(text):
        if match.group(1).strip() == heading.strip():
            return match.start(), match.end(), match.group(0)
    return None


def _known_pmids(data_dir: Path) -> set[str]:
    path = data_dir / "papers.json"
    if not path.exists() or not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    rows = data.get("papers") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return set()
    return {str(row["pmid"]) for row in rows if isinstance(row, dict) and row.get("pmid")}


def _one_digit_pmid_match(value: str, known: set[str]) -> str | None:
    matches = [
        pmid
        for pmid in known
        if len(pmid) == len(value) and sum(a != b for a, b in zip(pmid, value)) == 1
    ]
    return matches[0] if len(matches) == 1 else None


def _remove_pmid(text: str, pmid: str) -> str:
    text = re.sub(rf"(?m)^[-*]\s*PMID[:\s]*{re.escape(pmid)}\b.*(?:\n|$)", "", text)
    text = re.sub(rf"\s*\(\s*PMID[:\s]*{re.escape(pmid)}\s*\)", "", text, flags=re.IGNORECASE)
    return re.sub(rf"\bPMID[:\s]*{re.escape(pmid)}\b", "", text, flags=re.IGNORECASE)


def _repair_pmid_issue(data_dir: Path, issue: dict[str, Any]) -> bool:
    if issue.get("code") != "pmid_not_in_papers":
        return False
    filename = issue.get("file") or ""
    pmid = str(issue.get("value") or "")
    path = (data_dir / filename).resolve()
    if not pmid or not path.is_relative_to(data_dir) or path.suffix != ".md" or not path.exists():
        return False

    text = path.read_text(encoding="utf-8")
    replacement = _one_digit_pmid_match(pmid, _known_pmids(data_dir))
    repaired = text.replace(pmid, replacement) if replacement else _remove_pmid(text, pmid)
    if repaired == text:
        return False
    path.write_text(repaired, encoding="utf-8")
    return True


def _remove_inline_pmid(value: str, pmid: str) -> str:
    token = rf"PMID:\s*{re.escape(pmid)}\b"
    for pattern in (
        rf"\s*[;,]\s*{token}",
        rf"{token}\s*[;,]\s*",
        rf"\(\s*{token}\s*\)",
        token,
    ):
        repaired, count = re.subn(pattern, "", value, count=1, flags=re.IGNORECASE)
        if count:
            return re.sub(r"\(\s*\)", "", repaired)
    return value


def _repair_inline_citation_issue(
    data_dir: Path,
    issue: dict[str, Any],
    claim_validation: list[dict[str, Any]],
) -> bool:
    if not str(issue.get("code", "")).startswith("inline_citation_"):
        return False
    filename = issue.get("file") or ""
    inline_pmid = str(issue.get("inline_pmid") or "")
    value = str(issue.get("value") or "")
    path = (data_dir / filename).resolve()
    if (
        not inline_pmid
        or not value
        or not path.is_relative_to(data_dir)
        or path.suffix != ".md"
        or not path.exists()
    ):
        return False

    key = (issue.get("file"), issue.get("section"), issue.get("source_claim_index"))
    sibling_supported = any(
        (row.get("file"), row.get("section"), row.get("source_claim_index")) == key
        and row.get("status") == "supported"
        and row.get("inline_pmid") != issue.get("inline_pmid")
        for row in claim_validation
    )
    if not sibling_supported:
        return False

    text = path.read_text(encoding="utf-8")
    claim_at = text.find(value)
    if claim_at < 0:
        return False
    repaired_value = _remove_inline_pmid(value, inline_pmid)
    if repaired_value == value:
        return False
    repaired = text[:claim_at] + repaired_value + text[claim_at + len(value) :]
    path.write_text(repaired, encoding="utf-8")
    return True


def _build_prompt(issue: dict[str, Any], section_text: str) -> str:
    return f"""Rewrite only this markdown section to fix the validation issue.

Keep the same section heading. Keep evidence-grounded scientific tone.
For claim_rag_* issues, use only the evidence in the validation issue.
Do not replace the cited paper or add a new PMID to rescue a claim.
Rewrite causal or mechanistic report-derived claims as associations or hypotheses.
Do not claim treatment sensitivity, resistance, patient stratification, or therapeutic vulnerability unless the validation issue provides direct support for that exact claim.
Do not invent new PMIDs, p-values, scores, files, or pathway significance.
Do not add therapeutic/druggability conclusions to Part3.

Validation issue:
{json.dumps(issue, indent=2, ensure_ascii=False)}

Section:
{section_text}

Return only the corrected markdown section."""


def _create_model(provider: str | None) -> Any:
    from src.agents.model import create_llm

    return create_llm(provider)


def repair_report(
    data_dir: Path,
    issues_path: Path,
    *,
    llm: Any | None = None,
    provider: str | None = None,
    claim_validation: list[dict[str, Any]] | None = None,
) -> int:
    data_dir = data_dir.resolve()
    issues = _load_issues(issues_path)
    model = llm
    changed = 0
    claim_validation = claim_validation or []
    section_issues: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for issue in issues:
        if issue.get("severity") != "error":
            continue
        if _repair_pmid_issue(data_dir, issue):
            changed += 1
            continue
        if _repair_inline_citation_issue(data_dir, issue, claim_validation):
            changed += 1
            continue
        section = issue.get("section") or ""
        filename = issue.get("file") or ""
        if not section or not filename:
            continue
        section_issues.setdefault((filename, section), []).append(issue)

    for (filename, section), grouped_issues in section_issues.items():
        path = (data_dir / filename).resolve()
        if not path.is_relative_to(data_dir) or path.suffix != ".md" or not path.exists():
            continue

        text = path.read_text(encoding="utf-8")
        found = _find_section(text, section)
        if found is None:
            continue
        start, end, section_text = found
        if model is None:
            model = _create_model(provider)
        issue_payload: dict[str, Any] = (
            grouped_issues[0] if len(grouped_issues) == 1 else {"issues": grouped_issues}
        )
        replacement = _content(model.invoke(_build_prompt(issue_payload, section_text))).strip()
        if not replacement.startswith(section.strip()):
            replacement = section.strip() + "\n" + replacement
        path.write_text(text[:start] + replacement.rstrip() + "\n" + text[end:], encoding="utf-8")
        changed += 1

    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repair only validator-flagged report sections.")
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--issues", type=Path, required=True)
    parser.add_argument("--provider", default=None)
    args = parser.parse_args(argv)

    changed = repair_report(args.data_dir, args.issues, provider=args.provider)
    print(json.dumps({"changed_sections": changed}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
HEADING_RE = re.compile(r"^#{1,6}\s+.+?$", re.MULTILINE)
REPAIRABLE_INLINE_CITATION_CODES = {
    "inline_citation_unsupported",
    "inline_citation_overclaimed",
}


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


def _markdown_headings(text: str) -> list[str]:
    return [match.group(0).strip() for match in HEADING_RE.finditer(text)]


def _append_repair_trace(data_dir: Path, row: dict[str, Any]) -> None:
    trace_path = data_dir / "repair_trace.jsonl"
    if not trace_path.exists() or not trace_path.is_file():
        return
    with trace_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _target_spans(section_text: str, target_text: str) -> tuple[str, list[tuple[int, int]]]:
    if not target_text:
        return "missing", []

    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        found = section_text.find(target_text, start)
        if found < 0:
            break
        spans.append((found, found + len(target_text)))
        start = found + len(target_text)
    if spans:
        return "exact", spans

    tokens = [re.escape(token) for token in re.split(r"\s+", target_text.strip()) if token]
    if not tokens:
        return "missing", []
    soft_gap = r"(?:[^\S\r\n]+|[^\S\r\n]*\r?\n[^\S\r\n]*)"
    pattern = soft_gap.join(tokens)
    spans = [match.span() for match in re.finditer(pattern, section_text)]
    return ("whitespace_normalized", spans) if spans else ("missing", [])


def _pmids(text: str) -> set[str]:
    return set(re.findall(r"\bPMID[:\s]*(\d{6,9})\b", text, flags=re.IGNORECASE))


def _safe_claim_replacement(original: str, candidate: str) -> bool:
    candidate = candidate.strip()
    if not candidate or _markdown_headings(candidate):
        return False
    if not _pmids(candidate).issubset(_pmids(original)):
        return False
    original_size = len(re.sub(r"\s+", "", original))
    candidate_size = len(re.sub(r"\s+", "", candidate))
    return candidate_size >= 0.5 * original_size


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
    if issue.get("code") not in REPAIRABLE_INLINE_CITATION_CODES:
        return False
    filename = issue.get("file") or ""
    section = str(issue.get("section") or "")
    inline_pmid = str(issue.get("inline_pmid") or "")
    value = str(issue.get("value") or "")
    path = (data_dir / filename).resolve()
    if (
        not section
        or not inline_pmid
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
    found = _find_section(text, section)
    if found is None:
        return False
    start, end, section_text = found
    claim_at = section_text.find(value)
    if claim_at < 0:
        return False
    repaired_value = _remove_inline_pmid(value, inline_pmid)
    if repaired_value == value:
        return False
    repaired_section = (
        section_text[:claim_at] + repaired_value + section_text[claim_at + len(value) :]
    )
    repaired = text[:start] + repaired_section + text[end:]
    path.write_text(repaired, encoding="utf-8")
    return True


def _repair_inline_citation_issues(
    data_dir: Path,
    issues: list[dict[str, Any]],
    claim_validation: list[dict[str, Any]],
) -> bool:
    if not issues:
        return False
    first = issues[0]
    filename = first.get("file") or ""
    section = str(first.get("section") or "")
    value = str(first.get("value") or "")
    path = (data_dir / filename).resolve()
    if (
        not section
        or not value
        or not path.is_relative_to(data_dir)
        or path.suffix != ".md"
        or not path.exists()
    ):
        return False

    failed_pmids = {issue.get("inline_pmid") for issue in issues}
    key = (first.get("file"), first.get("section"), first.get("source_claim_index"))
    sibling_supported = any(
        (row.get("file"), row.get("section"), row.get("source_claim_index")) == key
        and row.get("status") == "supported"
        and row.get("inline_pmid") not in failed_pmids
        for row in claim_validation
    )
    if not sibling_supported:
        return False

    repaired_value = value
    for issue in issues:
        inline_pmid = str(issue.get("inline_pmid") or "")
        if not inline_pmid:
            return False
        repaired_value = _remove_inline_pmid(repaired_value, inline_pmid)
    if repaired_value == value:
        return False

    text = path.read_text(encoding="utf-8")
    found = _find_section(text, section)
    if found is None:
        return False
    start, end, section_text = found
    if section_text.count(value) != 1:
        return False
    repaired_section = section_text.replace(value, repaired_value, 1)
    path.write_text(text[:start] + repaired_section + text[end:], encoding="utf-8")
    return True


def _build_claim_prompt(issues: list[dict[str, Any]], claim: str) -> str:
    return f"""Rewrite only this exact claim to fix unresolved claim validation issues.

Preserve supported quantitative observations.
Preserve measured/statistical content.
Keep dataset-derived observations separate from literature-supported context.
For claim_rag_* issues, use only the evidence in the validation issue.
Rewrite causal or mechanistic report-derived claims as associations or hypotheses.
Remove or hedge only the unsupported interpretation.
Do not replace the cited paper or add any new PMID.
Do not claim treatment sensitivity, resistance, patient stratification, or therapeutic vulnerability unless the validation issue provides direct support for that exact claim.
Do not invent new PMIDs, p-values, scores, files, or pathway significance.
For unsupported_pathway_factor_significance, Keep L-R pathway annotations and measured factor-pathway results in separate sentences.
Do not place an unsupported pathway label and factor label in the same sentence unless that sentence explicitly states that no measured association was identified.
Do not delete the claim; make the narrowest supported correction.
Return only the corrected claim Markdown. Do not include a section heading.

Validation issues:
{json.dumps(issues, indent=2, ensure_ascii=False)}

Claim:
{claim}"""


def _trace_target_rejection(
    data_dir: Path,
    issue: dict[str, Any],
    reason: str,
    *,
    match_mode: str | None = None,
    occurrence_count: int | None = None,
    issue_count: int | None = None,
    path: str | None = None,
    retention_ratio: float | None = None,
) -> None:
    row: dict[str, Any] = {
        "event": "target_repair_rejected",
        "file": path or issue.get("file"),
        "section": issue.get("section"),
        "code": issue.get("code"),
        "reason": reason,
    }
    if match_mode is not None:
        row["match_mode"] = match_mode
    if occurrence_count is not None:
        row["occurrence_count"] = occurrence_count
    if issue_count is not None:
        row["issue_count"] = issue_count
    if retention_ratio is not None:
        row["retention_ratio"] = retention_ratio
    _append_repair_trace(data_dir, row)


def _retention_ratio(original: str, candidate: str) -> float:
    original_size = len(re.sub(r"\s+", "", original))
    candidate_size = len(re.sub(r"\s+", "", candidate))
    return candidate_size / original_size if original_size else 0.0


def _create_model(provider: str | None) -> Any:
    from src.agents.model import create_llm

    return create_llm(provider)


def repair_issues(
    data_dir: Path,
    issues: list[dict[str, Any]],
    *,
    llm: Any | None = None,
    provider: str | None = None,
    claim_validation: list[dict[str, Any]] | None = None,
) -> int:
    data_dir = data_dir.resolve()
    model = llm
    changed = 0
    claim_validation = claim_validation or []
    target_issues: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    inline_issues: dict[tuple[str, str, str, Any], list[dict[str, Any]]] = {}

    for issue in issues:
        if issue.get("severity") != "error":
            continue
        if _repair_pmid_issue(data_dir, issue):
            changed += 1
            continue
        if issue.get("code") in REPAIRABLE_INLINE_CITATION_CODES:
            key = (
                str(issue.get("file") or ""),
                str(issue.get("section") or ""),
                str(issue.get("value") or ""),
                issue.get("source_claim_index"),
            )
            inline_issues.setdefault(key, []).append(issue)
            continue
        target_text = str(issue.get("target_text") or "")
        if target_text:
            filename = str(issue.get("file") or "")
            section = str(issue.get("section") or "")
            if filename and section:
                target_issues.setdefault((filename, section, target_text), []).append(issue)
            else:
                _trace_target_rejection(data_dir, issue, "unhandled_repair_target")
            continue
        _trace_target_rejection(data_dir, issue, "unhandled_repair_target")

    for grouped_issues in inline_issues.values():
        if _repair_inline_citation_issues(data_dir, grouped_issues, claim_validation):
            changed += 1
            continue
        for issue in grouped_issues:
            target_text = str(issue.get("target_text") or "")
            if target_text:
                filename = str(issue.get("file") or "")
                section = str(issue.get("section") or "")
                if filename and section:
                    target_issues.setdefault((filename, section, target_text), []).append(issue)
                else:
                    _trace_target_rejection(data_dir, issue, "unhandled_repair_target")
            else:
                _trace_target_rejection(data_dir, issue, "unhandled_repair_target")

    for (filename, section, target_text), grouped_issues in target_issues.items():
        first = grouped_issues[0]
        path = (data_dir / filename).resolve()
        if not path.is_relative_to(data_dir) or path.suffix != ".md" or not path.exists():
            _trace_target_rejection(data_dir, first, "unhandled_repair_target", path=filename)
            continue

        text = path.read_text(encoding="utf-8")
        found = _find_section(text, section)
        if found is None:
            _trace_target_rejection(data_dir, first, "target_missing", path=filename)
            continue
        start, end, section_text = found
        match_mode, spans = _target_spans(section_text, target_text)
        occurrence_count = len(spans)
        issue_count = len(grouped_issues)
        if occurrence_count == 0:
            _trace_target_rejection(
                data_dir,
                first,
                "target_missing",
                match_mode=match_mode,
                occurrence_count=occurrence_count,
                issue_count=issue_count,
                path=filename,
            )
            continue
        if match_mode == "whitespace_normalized" and occurrence_count != 1:
            _trace_target_rejection(
                data_dir,
                first,
                "ambiguous_target",
                match_mode=match_mode,
                occurrence_count=occurrence_count,
                issue_count=issue_count,
                path=filename,
            )
            continue
        if occurrence_count > 1 and occurrence_count != issue_count:
            _trace_target_rejection(
                data_dir,
                first,
                "target_count_mismatch",
                match_mode=match_mode,
                occurrence_count=occurrence_count,
                issue_count=issue_count,
                path=filename,
            )
            continue

        deterministic = [issue.get("replacement_text") for issue in grouped_issues]
        deterministic = [value for value in deterministic if isinstance(value, str)]
        if deterministic:
            if len(set(deterministic)) != 1 or len(deterministic) != issue_count:
                _trace_target_rejection(
                    data_dir,
                    first,
                    "replacement_mismatch",
                    match_mode=match_mode,
                    occurrence_count=occurrence_count,
                    issue_count=issue_count,
                    path=filename,
                )
                continue
            replacement = deterministic[0].strip()
            path_kind = "deterministic"
        else:
            if model is None:
                model = _create_model(provider)
            replacement = _content(model.invoke(_build_claim_prompt(grouped_issues, target_text))).strip()
            path_kind = "llm"

        ratio = _retention_ratio(target_text, replacement)
        if not _safe_claim_replacement(target_text, replacement):
            _trace_target_rejection(
                data_dir,
                first,
                "unsafe_replacement",
                match_mode=match_mode,
                occurrence_count=occurrence_count,
                issue_count=issue_count,
                path=filename,
                retention_ratio=ratio,
            )
            continue

        repaired_section = section_text
        for span_start, span_end in reversed(spans):
            repaired_section = (
                repaired_section[:span_start] + replacement + repaired_section[span_end:]
            )
        repaired_text = text[:start] + repaired_section + text[end:]
        if _markdown_headings(repaired_text) != _markdown_headings(text):
            _trace_target_rejection(
                data_dir,
                first,
                "heading_mismatch",
                match_mode=match_mode,
                occurrence_count=occurrence_count,
                issue_count=issue_count,
                path=filename,
                retention_ratio=ratio,
            )
            continue
        path.write_text(repaired_text, encoding="utf-8")
        _append_repair_trace(
            data_dir,
            {
                "event": "target_repair_applied",
                "file": filename,
                "section": section,
                "code": first.get("code"),
                "match_mode": "repeated_exact" if match_mode == "exact" and occurrence_count > 1 else match_mode,
                "occurrence_count": occurrence_count,
                "issue_count": issue_count,
                "path": path_kind,
                "retention_ratio": ratio,
            },
        )
        changed += 1

    return changed


def repair_report(
    data_dir: Path,
    issues_path: Path,
    *,
    llm: Any | None = None,
    provider: str | None = None,
    claim_validation: list[dict[str, Any]] | None = None,
) -> int:
    return repair_issues(
        data_dir,
        _load_issues(issues_path),
        llm=llm,
        provider=provider,
        claim_validation=claim_validation,
    )


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

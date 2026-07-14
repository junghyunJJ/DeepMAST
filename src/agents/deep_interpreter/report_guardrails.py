from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from scripts import repair_report as repair_report_script
from scripts import validate_report as validate_report_script


REQUIRED_REPORT_FILES = (
    "papers.json",
    "part1_final.md",
    "part2_final.md",
    "part3_final.md",
)
SYNTHESIS_REQUIRED_FILES = ("papers.json", "synthesis.md")
MAX_GUARDRAIL_REPAIR_PASSES = 3
SYNTHESIS_GUARDRAIL_SENTENCE = "this remains a hypothesis requiring validation."
SYNTHESIS_THERAPEUTIC_OVERCLAIM_RE = re.compile(
    r"\b(high-confidence therapeutic target|clinical prioritization|most effective|"
    r"would be particularly sensitive to|therapy[-\s]+resistant|treatment[-\s]+sensitive|"
    r"validated therapeutic|proves therapeutic|therapeutic vulnerability|therapeutic target)\b",
    re.IGNORECASE,
)
SYNTHESIS_NEGATED_THERAPEUTIC_RE = re.compile(
    r"\b(?:does\s+not|do\s+not|did\s+not|cannot|can\s+not|no|not|without)\b"
    r".{0,80}\b(?:establish|support|validate|confirm|prove|demonstrate|show|indicate|"
    r"therapeutic vulnerability|therapeutic target)\b",
    re.IGNORECASE,
)
SYNTHESIS_HTML_FRAGMENT_RE = re.compile(
    r"^\s*<(?:article|div|h[1-6]|li|ol|p|section|table|ul)\b|"
    r"</(?:article|div|h[1-6]|li|ol|p|section|table|ul)>",
    re.IGNORECASE | re.MULTILINE,
)


def _issue_payload(issues: list[dict[str, str]]) -> dict[str, Any]:
    return {"issue_count": len(issues), "issues": issues}


def _write_issues(path: Path, issues: list[dict[str, str]]) -> None:
    path.write_text(
        json.dumps(_issue_payload(issues), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _error_count(issues: list[dict[str, str]]) -> int:
    return sum(1 for issue in issues if issue.get("severity") == "error")


def _missing_required_files(data_dir: Path) -> list[str]:
    return [name for name in REQUIRED_REPORT_FILES if not (data_dir / name).exists()]


def _missing_synthesis_required_files(data_dir: Path) -> list[str]:
    return [name for name in SYNTHESIS_REQUIRED_FILES if not (data_dir / name).exists()]


def _section_for_claim(text: str, claim: str) -> str:
    claim_at = text.find(claim)
    if claim_at < 0:
        return ""
    heading = ""
    for match in re.finditer(r"^## .+$", text, flags=re.MULTILINE):
        if match.start() > claim_at:
            break
        heading = match.group(0).strip()
    return heading


def _is_hedged_claim(claim: str, following: str = "") -> bool:
    return bool(
        validate_report_script.MECHANISTIC_HEDGE_RE.search(claim)
        or SYNTHESIS_GUARDRAIL_SENTENCE in following.lower()
    )


def _is_negated_therapeutic_claim(claim: str) -> bool:
    return bool(SYNTHESIS_NEGATED_THERAPEUTIC_RE.search(claim))


def _synthesis_issue(
    *,
    code: str,
    section: str,
    value: str,
    severity: str = "error",
    evidence: str = "",
    repair_instruction: str = "",
) -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "file": "synthesis.md",
        "section": section,
        "value": value,
        "evidence": evidence,
        "repair_instruction": repair_instruction,
    }


def validate_synthesis_report(data_dir: str | Path) -> list[dict[str, str]]:
    data_dir = Path(data_dir).expanduser().resolve()
    text = (data_dir / "synthesis.md").read_text(encoding="utf-8")
    issues: list[dict[str, str]] = []

    if SYNTHESIS_HTML_FRAGMENT_RE.search(text):
        issues.append(
            _synthesis_issue(
                code="synthesis_not_markdown",
                section="",
                value="synthesis.md contains HTML block tags.",
                evidence="REPORTER must persist synthesis.md as Markdown; HTML belongs only in the rendered report.",
                repair_instruction="Rewrite synthesis.md as Markdown before generating HTML.",
            )
        )

    known_pmids = validate_report_script._papers_pmids(data_dir, issues)
    if known_pmids is not None:
        for pmid in sorted(set(validate_report_script.PMID_RE.findall(text))):
            if pmid not in known_pmids:
                issues.append(
                    _synthesis_issue(
                        code="pmid_not_in_papers",
                        section="",
                        value=pmid,
                        evidence=f"{pmid} is cited in synthesis.md but absent from papers.json.",
                        repair_instruction="Remove the unsupported PMID or replace it with a PMID present in papers.json.",
                    )
                )

    claims = validate_report_script._claim_windows(text)
    for index, claim in enumerate(claims):
        if not validate_report_script.REPORT_EVIDENCE_RE.search(claim):
            continue
        if _is_negated_therapeutic_claim(claim):
            continue
        mechanistic_overclaim = validate_report_script.MECHANISTIC_TRIGGER_RE.search(claim)
        therapeutic_overclaim = SYNTHESIS_THERAPEUTIC_OVERCLAIM_RE.search(claim)
        if not (mechanistic_overclaim or therapeutic_overclaim):
            continue
        following = claims[index + 1].lower() if index + 1 < len(claims) else ""
        warning = _is_hedged_claim(claim, following)
        issues.append(
            _synthesis_issue(
                code=(
                    "synthesis_overclaim_warning"
                    if warning
                    else "unsupported_synthesis_overclaim"
                ),
                section=_section_for_claim(text, claim),
                value=claim,
                severity="warning" if warning else "error",
                evidence="Synthesis report-derived spatial/statistical evidence was written as a mechanistic or therapeutic claim.",
                repair_instruction=(
                    "Rewrite as an association or hypothesis unless direct experimental evidence supports this exact claim."
                ),
            )
        )
    return issues


def repair_synthesis_report(data_dir: str | Path, issues: list[dict[str, str]]) -> int:
    data_dir = Path(data_dir).expanduser().resolve()
    changed_claims = 0

    path = data_dir / "synthesis.md"
    current = path.read_text(encoding="utf-8")
    cursor = 0
    for issue in issues:
        if issue.get("severity") != "error" or issue.get("code") != "unsupported_synthesis_overclaim":
            continue
        claim = issue.get("value") or ""
        if not claim or SYNTHESIS_GUARDRAIL_SENTENCE in claim.lower():
            continue
        claim_at = current.find(claim, cursor)
        if claim_at < 0:
            continue
        replacement = f"{claim} {SYNTHESIS_GUARDRAIL_SENTENCE}"
        current = current[:claim_at] + replacement + current[claim_at + len(claim) :]
        cursor = claim_at + len(replacement)
        changed_claims += 1

    if changed_claims:
        path.write_text(current, encoding="utf-8")

    for issue in issues:
        if issue.get("severity") != "error":
            continue
        if repair_report_script._repair_pmid_issue(data_dir, issue):
            changed_claims += 1
    return changed_claims


def run_report_guardrail(data_dir: str | Path, *, provider: str | None = None) -> dict[str, Any]:
    data_dir = Path(data_dir).expanduser().resolve()
    missing = _missing_required_files(data_dir)
    if missing:
        return {"status": "skipped", "missing": missing}

    initial_path = data_dir / "report_validation_initial.json"
    final_path = data_dir / "report_validation_final.json"

    initial_issues = validate_report_script.validate_report(data_dir)
    _write_issues(initial_path, initial_issues)
    initial_error_count = _error_count(initial_issues)

    current_issues = initial_issues
    issues_path = initial_path
    changed_sections = 0
    repair_attempt_count = 0

    while (
        _error_count(current_issues)
        and repair_attempt_count < MAX_GUARDRAIL_REPAIR_PASSES
    ):
        changed = repair_report_script.repair_report(
            data_dir,
            issues_path,
            provider=provider,
        )
        repair_attempt_count += 1
        changed_sections += changed
        current_issues = validate_report_script.validate_report(data_dir)
        _write_issues(final_path, current_issues)
        if changed == 0:
            break
        issues_path = final_path

    final_issues = current_issues
    _write_issues(final_path, final_issues)
    final_error_count = _error_count(final_issues)

    return {
        "status": "failed" if final_error_count else "passed",
        "initial_issue_count": len(initial_issues),
        "initial_error_count": initial_error_count,
        "repair_attempt_count": repair_attempt_count,
        "changed_sections": changed_sections,
        "final_issue_count": len(final_issues),
        "final_error_count": final_error_count,
    }


def run_synthesis_guardrail(data_dir: str | Path, *, provider: str | None = None) -> dict[str, Any]:
    _ = provider
    data_dir = Path(data_dir).expanduser().resolve()
    missing = _missing_synthesis_required_files(data_dir)
    if missing:
        return {"status": "skipped", "missing": missing}

    initial_path = data_dir / "synthesis_guardrail_initial.json"
    final_path = data_dir / "synthesis_guardrail_final.json"

    initial_issues = validate_synthesis_report(data_dir)
    _write_issues(initial_path, initial_issues)
    initial_error_count = _error_count(initial_issues)

    current_issues = initial_issues
    changed_claims = 0
    repair_attempt_count = 0

    while (
        _error_count(current_issues)
        and repair_attempt_count < MAX_GUARDRAIL_REPAIR_PASSES
    ):
        changed = repair_synthesis_report(data_dir, current_issues)
        repair_attempt_count += 1
        changed_claims += changed
        current_issues = validate_synthesis_report(data_dir)
        if changed == 0:
            break

    final_issues = current_issues
    _write_issues(final_path, final_issues)
    final_error_count = _error_count(final_issues)

    return {
        "status": "failed" if final_error_count else "passed",
        "artifact": "synthesis.md",
        "initial_issue_count": len(initial_issues),
        "initial_error_count": initial_error_count,
        "repair_attempt_count": repair_attempt_count,
        "changed_claims": changed_claims,
        "final_issue_count": len(final_issues),
        "final_error_count": final_error_count,
    }

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from scripts import repair_report as repair_report_script
from scripts import validate_report as validate_report_script
from src.agents.deep_interpreter import claim_rag_validation
from src.agents.deep_interpreter import synthesis_consistency_validation


REQUIRED_PART_FILES = (
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
EXPLICIT_INLINE_CONTRADICTION_RE = re.compile(
    r"\b(contradict|incorrectly states)\b",
    re.IGNORECASE,
)
PAPERS_JSON_LOAD_ERROR_CODES = {
    "papers_json_missing",
    "papers_json_unreadable",
    "papers_json_malformed",
    "papers_json_invalid",
}


def _issue_payload(
    issues: list[dict[str, str]],
    claim_validation: list[dict[str, Any]] | None = None,
    consistency_validation: list[dict[str, Any]] | None = None,
    claim_selection: dict[str, Any] | None = None,
    inline_citation_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"issue_count": len(issues), "issues": issues}
    if claim_validation is not None:
        payload["claim_validation"] = claim_validation
    if consistency_validation is not None:
        payload["consistency_validation"] = consistency_validation
    if claim_selection is not None:
        payload["claim_selection"] = claim_selection
    if inline_citation_coverage is not None:
        payload["inline_citation_coverage"] = inline_citation_coverage
    return payload


def _write_issues(
    path: Path,
    issues: list[dict[str, str]],
    claim_validation: list[dict[str, Any]] | None = None,
    consistency_validation: list[dict[str, Any]] | None = None,
    claim_selection: dict[str, Any] | None = None,
    inline_citation_coverage: dict[str, Any] | None = None,
) -> None:
    path.write_text(
        json.dumps(
            _issue_payload(
                issues,
                claim_validation,
                consistency_validation,
                claim_selection,
                inline_citation_coverage,
            ),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _error_count(issues: list[dict[str, str]]) -> int:
    return sum(1 for issue in issues if issue.get("severity") == "error")


def _issue_claim_key(issue: dict[str, str]) -> tuple[str, str, str]:
    return (
        str(issue.get("file") or ""),
        str(issue.get("section") or ""),
        str(issue.get("value") or ""),
    )


def _missing_required_files(data_dir: Path, filenames: tuple[str, ...]) -> list[str]:
    return [name for name in filenames if not (data_dir / name).exists()]


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
    target_text: str = "",
    replacement_text: str = "",
) -> dict[str, str]:
    issue = {
        "code": code,
        "severity": severity,
        "file": "synthesis.md",
        "section": section,
        "value": value,
        "evidence": evidence,
        "repair_instruction": repair_instruction,
    }
    if target_text:
        issue["target_text"] = target_text
    if replacement_text:
        issue["replacement_text"] = replacement_text
    return issue


def _validate_part_reports(
    data_dir: Path,
    *,
    provider: str | None,
    claim_cache: dict[str, list[dict[str, Any]]],
    filenames: tuple[str, ...],
) -> tuple[
    list[dict[str, str]],
    list[dict[str, Any]],
    dict[str, Any] | None,
    dict[str, Any] | None,
]:
    deterministic = [
        issue
        for issue in validate_report_script.validate_report(data_dir)
        if issue.get("file") not in REQUIRED_PART_FILES or issue.get("file") in filenames
    ]
    if any(issue.get("code") in PAPERS_JSON_LOAD_ERROR_CODES for issue in deterministic):
        return deterministic, [], None, None
    semantic = claim_rag_validation.validate_claims(
        data_dir,
        filenames,
        provider=provider,
        cache=claim_cache,
    )
    return (
        deterministic + semantic["issues"],
        semantic["claims"],
        semantic.get("selection"),
        semantic.get("inline_citation_coverage"),
    )


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
                target_text="" if warning else claim,
            )
        )
    return issues


def _exact_evidence_fallback(pmid: str, evidence_quote: str) -> str:
    fact = " ".join(evidence_quote.split()).strip()
    fact = re.sub(
        rf"\s*\(PMID:\s*{re.escape(pmid)}\)\s*[.!?]?\s*$",
        "",
        fact,
        flags=re.IGNORECASE,
    )
    fact = fact.strip().rstrip(".!?")
    if not fact:
        return ""
    return (
        f"{fact} (PMID: {pmid}). "
        "This remains a hypothesis requiring validation."
    )


def _repair_explicit_inline_contradiction(
    data_dir: Path,
    issue: dict[str, str],
    *,
    provider: str | None = None,
    deterministic_only: bool = False,
) -> bool:
    if issue.get("code") != "inline_citation_overclaimed":
        return False
    pmid = str(issue.get("inline_pmid") or "")
    evidence_quote = str(issue.get("evidence_quote") or "")
    claim = str(issue.get("value") or "")
    reason = str(issue.get("reason") or "")
    if not (
        pmid
        and evidence_quote
        and claim
        and EXPLICIT_INLINE_CONTRADICTION_RE.search(reason)
    ):
        return False

    path = data_dir / "synthesis.md"
    text = path.read_text(encoding="utf-8")
    claim_at = text.find(claim)
    if claim_at < 0:
        return False

    replacement = ""
    if not deterministic_only:
        prompt = f"""Rewrite only this claim using the supplied evidence quote and the exact PMID.
Keep only facts explicitly stated in the quote. Preserve PMID: {pmid} on the factual sentence.
Move any unsupported mechanism, prognosis extension, or therapeutic implication to exactly:
This remains a hypothesis requiring validation.
Return complete Markdown replacement text only.

Claim:
{claim}

Evidence quote:
{evidence_quote}
"""
        try:
            model = repair_report_script._create_model(provider)
            replacement = repair_report_script._content(model.invoke(prompt)).strip()
        except Exception:
            replacement = ""

    if not replacement or pmid not in replacement:
        replacement = _exact_evidence_fallback(pmid, evidence_quote)
    if not replacement:
        return False
    path.write_text(text[:claim_at] + replacement + text[claim_at + len(claim) :], encoding="utf-8")
    return True


def repair_synthesis_report(
    data_dir: str | Path,
    issues: list[dict[str, str]],
    claim_validation: list[dict[str, Any]] | None = None,
    *,
    provider: str | None = None,
    deterministic_contradictions: bool = False,
) -> int:
    data_dir = Path(data_dir).expanduser().resolve()
    changed_claims = 0
    claim_validation = claim_validation or []

    for issue in issues:
        if issue.get("severity") != "error":
            continue
        if repair_report_script._repair_inline_citation_issue(
            data_dir,
            issue,
            claim_validation,
        ):
            changed_claims += 1
            continue
        if _repair_explicit_inline_contradiction(
            data_dir,
            issue,
            provider=provider,
            deterministic_only=deterministic_contradictions,
        ):
            changed_claims += 1

    generic_issues: list[dict[str, str]] = []
    for issue in issues:
        target_text = issue.get("target_text") or ""
        filename = issue.get("file") or ""
        section = issue.get("section") or ""
        path = (data_dir / filename).resolve()
        if (
            issue.get("severity") == "error"
            and issue.get("code") != "unsupported_synthesis_overclaim"
            and target_text
            and filename
            and section
            and path.is_relative_to(data_dir)
            and path.suffix == ".md"
            and path.exists()
            and target_text in path.read_text(encoding="utf-8")
        ):
            generic_issues.append(issue)
    if generic_issues:
        changed_claims += repair_report_script.repair_issues(
            data_dir,
            generic_issues,
            provider=provider,
            claim_validation=claim_validation,
        )

    path = data_dir / "synthesis.md"
    current = path.read_text(encoding="utf-8")
    cursor = 0
    for issue in issues:
        if issue.get("severity") != "error" or issue.get("code") not in {
            "unsupported_synthesis_overclaim",
            "claim_rag_overclaimed",
            "claim_rag_unsupported",
            "inline_citation_unsupported",
            "inline_citation_overclaimed",
        }:
            continue
        if (
            issue.get("target_text")
            and issue.get("code") != "unsupported_synthesis_overclaim"
        ):
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
    changed_claims += synthesis_consistency_validation.repair_synthesis_consistency(
        data_dir, issues
    )
    return changed_claims


def _claim_status_counts(claims: list[dict[str, Any]]) -> dict[str, int]:
    statuses = ("supported", "overclaimed", "unsupported", "unverifiable")
    return {
        status: sum(1 for claim in claims if claim.get("status") == status)
        for status in statuses
    }


def _validate_synthesis_guardrails(
    data_dir: Path,
    *,
    provider: str | None,
    claim_cache: dict[str, list[dict[str, Any]]],
) -> tuple[
    list[dict[str, str]],
    list[dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, Any] | None,
    dict[str, Any] | None,
]:
    deterministic = validate_synthesis_report(data_dir)
    if any(
        issue.get("code") in PAPERS_JSON_LOAD_ERROR_CODES
        or issue.get("code") == "synthesis_not_markdown"
        for issue in deterministic
    ):
        return deterministic, [], {"issues": [], "results": []}, None, None
    semantic = claim_rag_validation.validate_claims(
        data_dir,
        ("synthesis.md",),
        provider=provider,
        cache=claim_cache,
    )
    consistency = synthesis_consistency_validation.validate_synthesis_consistency(data_dir)
    return (
        deterministic + semantic["issues"] + consistency["issues"],
        semantic["claims"],
        consistency,
        semantic.get("selection"),
        semantic.get("inline_citation_coverage"),
    )


def run_report_guardrail(
    data_dir: str | Path,
    *,
    provider: str | None = None,
    filenames: tuple[str, ...] = REQUIRED_PART_FILES,
) -> dict[str, Any]:
    data_dir = Path(data_dir).expanduser().resolve()
    missing = _missing_required_files(data_dir, filenames)
    if missing:
        return {"status": "skipped", "missing": missing}

    initial_path = data_dir / "report_validation_initial.json"
    final_path = data_dir / "report_validation_final.json"

    claim_cache: dict[str, list[dict[str, Any]]] = {}
    initial_issues, initial_claims, initial_selection, initial_coverage = _validate_part_reports(
        data_dir,
        provider=provider,
        claim_cache=claim_cache,
        filenames=filenames,
    )
    _write_issues(
        initial_path,
        initial_issues,
        initial_claims,
        claim_selection=initial_selection,
        inline_citation_coverage=initial_coverage,
    )
    initial_error_count = _error_count(initial_issues)

    current_issues = initial_issues
    current_claims = initial_claims
    current_selection = initial_selection
    current_coverage = initial_coverage
    issues_path = initial_path
    changed_sections = 0
    repair_attempt_count = 0
    terminal_repair_count = 0
    last_repair_error_keys: set[tuple[str, str, str]] = set()

    while (
        _error_count(current_issues)
        and repair_attempt_count < MAX_GUARDRAIL_REPAIR_PASSES
    ):
        last_repair_error_keys = {
            _issue_claim_key(issue)
            for issue in current_issues
            if issue.get("severity") == "error"
        }
        changed = repair_report_script.repair_report(
            data_dir,
            issues_path,
            provider=provider,
            claim_validation=current_claims,
        )
        repair_attempt_count += 1
        changed_sections += changed
        current_issues, current_claims, current_selection, current_coverage = _validate_part_reports(
            data_dir,
            provider=provider,
            claim_cache=claim_cache,
            filenames=filenames,
        )
        _write_issues(
            final_path,
            current_issues,
            current_claims,
            claim_selection=current_selection,
            inline_citation_coverage=current_coverage,
        )
        if changed == 0:
            break
        issues_path = final_path

    newly_surfaced_errors = [
        issue
        for issue in current_issues
        if issue.get("severity") == "error"
        and _issue_claim_key(issue) not in last_repair_error_keys
    ]
    if repair_attempt_count == MAX_GUARDRAIL_REPAIR_PASSES and newly_surfaced_errors:
        terminal_repair_count = 1
        terminal_path = data_dir / "report_validation_terminal.json"
        _write_issues(
            terminal_path,
            newly_surfaced_errors,
            current_claims,
            claim_selection=current_selection,
            inline_citation_coverage=current_coverage,
        )
        terminal_changed = repair_report_script.repair_report(
            data_dir,
            terminal_path,
            provider=provider,
            claim_validation=current_claims,
        )
        changed_sections += terminal_changed
        if terminal_changed:
            current_issues, current_claims, current_selection, current_coverage = (
                _validate_part_reports(
                    data_dir,
                    provider=provider,
                    claim_cache=claim_cache,
                    filenames=filenames,
                )
            )

    final_issues = current_issues
    _write_issues(
        final_path,
        final_issues,
        current_claims,
        claim_selection=current_selection,
        inline_citation_coverage=current_coverage,
    )
    final_error_count = _error_count(final_issues)

    return {
        "status": "failed" if final_error_count else "passed",
        "initial_issue_count": len(initial_issues),
        "initial_error_count": initial_error_count,
        "repair_attempt_count": repair_attempt_count,
        "terminal_repair_count": terminal_repair_count,
        "changed_sections": changed_sections,
        "final_issue_count": len(final_issues),
        "final_error_count": final_error_count,
    }


def run_synthesis_guardrail(data_dir: str | Path, *, provider: str | None = None) -> dict[str, Any]:
    data_dir = Path(data_dir).expanduser().resolve()
    missing = _missing_synthesis_required_files(data_dir)
    if missing:
        return {"status": "skipped", "missing": missing}

    initial_path = data_dir / "synthesis_guardrail_initial.json"
    final_path = data_dir / "synthesis_guardrail_final.json"

    claim_cache: dict[str, list[dict[str, Any]]] = {}
    (
        initial_issues,
        initial_claims,
        initial_consistency,
        initial_selection,
        initial_coverage,
    ) = _validate_synthesis_guardrails(
        data_dir,
        provider=provider,
        claim_cache=claim_cache,
    )
    _write_issues(
        initial_path,
        initial_issues,
        initial_claims,
        initial_consistency["results"],
        claim_selection=initial_selection,
        inline_citation_coverage=initial_coverage,
    )
    initial_error_count = _error_count(initial_issues)

    current_issues = initial_issues
    current_claims = initial_claims
    current_consistency = initial_consistency
    current_selection = initial_selection
    current_coverage = initial_coverage
    changed_claims = 0
    repair_attempt_count = 0
    terminal_repair_count = 0
    last_repair_error_keys: set[tuple[str, str, str]] = set()

    while (
        _error_count(current_issues)
        and repair_attempt_count < MAX_GUARDRAIL_REPAIR_PASSES
    ):
        last_repair_error_keys = {
            _issue_claim_key(issue)
            for issue in current_issues
            if issue.get("severity") == "error"
        }
        changed = repair_synthesis_report(
            data_dir,
            current_issues,
            current_claims,
            provider=provider,
            deterministic_contradictions=repair_attempt_count > 0,
        )
        repair_attempt_count += 1
        changed_claims += changed
        (
            current_issues,
            current_claims,
            current_consistency,
            current_selection,
            current_coverage,
        ) = _validate_synthesis_guardrails(
            data_dir,
            provider=provider,
            claim_cache=claim_cache,
        )
        if changed == 0:
            break

    newly_surfaced_errors = [
        issue
        for issue in current_issues
        if issue.get("severity") == "error"
        and _issue_claim_key(issue) not in last_repair_error_keys
    ]
    if repair_attempt_count == MAX_GUARDRAIL_REPAIR_PASSES and newly_surfaced_errors:
        terminal_repair_count = 1
        terminal_changed = repair_synthesis_report(
            data_dir,
            newly_surfaced_errors,
            current_claims,
            provider=provider,
            deterministic_contradictions=True,
        )
        changed_claims += terminal_changed
        if terminal_changed:
            (
                current_issues,
                current_claims,
                current_consistency,
                current_selection,
                current_coverage,
            ) = _validate_synthesis_guardrails(
                data_dir,
                provider=provider,
                claim_cache=claim_cache,
            )

    final_issues = current_issues
    _write_issues(
        final_path,
        final_issues,
        current_claims,
        current_consistency["results"],
        claim_selection=current_selection,
        inline_citation_coverage=current_coverage,
    )
    final_error_count = _error_count(final_issues)

    return {
        "status": "failed" if final_error_count else "passed",
        "artifact": "synthesis.md",
        "initial_issue_count": len(initial_issues),
        "initial_error_count": initial_error_count,
        "repair_attempt_count": repair_attempt_count,
        "terminal_repair_count": terminal_repair_count,
        "changed_claims": changed_claims,
        "final_issue_count": len(final_issues),
        "final_error_count": final_error_count,
        "claims_validated": len(current_claims),
        "claims_by_status": _claim_status_counts(current_claims),
        "validation_results": current_claims,
        "claim_selection": current_selection,
        "inline_citation_coverage": current_coverage,
        "consistency_checked": True,
        "consistency_issue_count": len(initial_consistency["issues"]),
        "consistency_validation": current_consistency["results"],
    }

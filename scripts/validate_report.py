#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any


PMID_RE = re.compile(r"\bPMID[:\s]*(\d{6,9})\b", re.IGNORECASE)
SECTION_RE = re.compile(r"(^## .+?$)(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
THERAPEUTIC_RE = re.compile(
    r"\b(therapeutic|druggability|drug ranking|clinical prioritization|high-confidence therapeutic target)\b",
    re.IGNORECASE,
)
SIGNIFICANCE_RE = re.compile(r"\b(significant|significantly|enriched|enrichment)\b", re.IGNORECASE)
FACTOR1_RE = re.compile(r"\bFactor\s*1\b|\bFactor1\b", re.IGNORECASE)
PATHWAY_RE = re.compile(r"\b(TGFb|TGF-beta|MAPK|PI3K|Hypoxia)\b", re.IGNORECASE)
HYPOTHESIS_RE = re.compile(
    r"\b(may|might|could|hypothesis|inferred|suggests?|consistent with|not pathway-factor significance)\b",
    re.IGNORECASE,
)
NEGATED_SIGNIFICANCE_RE = re.compile(
    r"\b(?:no|not|without|lack|lacks|lacked|absent)\b.{0,40}\b(?:significant|significantly|enriched|enrichment)\b|"
    r"\b(?:significant|significantly|enriched|enrichment)\b.{0,40}\b(?:no|not|without|lack|lacks|lacked|absent)\b",
    re.IGNORECASE,
)


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_papers_json(path: Path) -> tuple[Any, str | None]:
    if not path.exists():
        return None, "papers_json_missing"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, "papers_json_unreadable"
    try:
        return json.loads(text), None
    except json.JSONDecodeError:
        return None, "papers_json_malformed"


def _papers_pmids(data_dir: Path, issues: list[dict[str, str]]) -> set[str] | None:
    data, error = _load_papers_json(data_dir / "papers.json")
    if error:
        issues.append(
            _issue(
                code=error,
                file="papers.json",
                section="",
                value="papers.json",
                evidence=f"papers.json is required for PMID grounding but could not be loaded ({error}).",
                repair_instruction="Regenerate or repair papers.json before validating report citations.",
            )
        )
        return None
    rows = data.get("papers") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        issues.append(
            _issue(
                code="papers_json_invalid",
                file="papers.json",
                section="",
                value=type(data).__name__,
                evidence="papers.json must be either a list of paper records or an object with a papers list.",
                repair_instruction="Regenerate papers.json in the expected SEARCHER-to-INTERPRETER handoff shape.",
            )
        )
        return None

    pmids: set[str] = set()
    for row in rows:
        if isinstance(row, dict) and row.get("pmid"):
            pmids.add(str(row["pmid"]))
    return pmids


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _sections(text: str) -> list[dict[str, str | int]]:
    matches = list(SECTION_RE.finditer(text))
    if not matches and text.strip():
        return [{"heading": "", "body": text, "start": 0, "end": len(text)}]
    return [
        {
            "heading": match.group(1).strip(),
            "body": match.group(2),
            "start": match.start(),
            "end": match.end(),
        }
        for match in matches
    ]


def _issue(
    *,
    code: str,
    file: str,
    section: str,
    value: str,
    severity: str = "error",
    evidence: str = "",
    repair_instruction: str = "",
) -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "file": file,
        "section": section,
        "value": value,
        "evidence": evidence,
        "repair_instruction": repair_instruction,
    }


def _check_pmids(data_dir: Path, issues: list[dict[str, str]]) -> None:
    known = _papers_pmids(data_dir, issues)
    if known is None:
        return

    for md in sorted(data_dir.glob("part*_final.md")):
        text = _read_text(md)
        for pmid in sorted(set(PMID_RE.findall(text))):
            if pmid not in known:
                issues.append(
                    _issue(
                        code="pmid_not_in_papers",
                        file=md.name,
                        section="",
                        value=pmid,
                        evidence=f"{pmid} is cited in {md.name} but absent from papers.json.",
                        repair_instruction="Remove the unsupported PMID or replace it with a PMID present in papers.json.",
                    )
                )


def _pathway_key(value: str) -> str:
    normalized = value.lower().replace("-", "").replace("_", "").replace(" ", "")
    if normalized in {"tgfb", "tgfbeta"}:
        return "TGFb"
    if normalized == "mapk":
        return "MAPK"
    if normalized == "pi3k":
        return "PI3K"
    if normalized == "hypoxia":
        return "Hypoxia"
    return value


def _mentioned_pathways(text: str) -> set[str]:
    return {_pathway_key(match) for match in PATHWAY_RE.findall(text)}


def _claim_windows(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def _factor1_supported_pathways(data_dir: Path) -> set[str]:
    path = data_dir / "sig_liana_pathway_factor.csv"
    if not path.exists():
        return set()
    supported: set[str] = set()
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            factor = str(row.get("factor") or row.get("Factor") or "")
            pathway = str(row.get("pathway") or row.get("Pathway") or "")
            if FACTOR1_RE.search(factor) and PATHWAY_RE.search(pathway):
                supported.update(_mentioned_pathways(pathway))
    return supported


def _check_factor1_pathway_claims(data_dir: Path, issues: list[dict[str, str]]) -> None:
    supported = _factor1_supported_pathways(data_dir)
    path = data_dir / "part2_final.md"
    text = _read_text(path)
    if not text:
        return
    for section in _sections(text):
        for window in _claim_windows(str(section["body"])):
            claimed = _mentioned_pathways(window)
            unsupported = sorted(claimed - supported)
            if not (
                FACTOR1_RE.search(window)
                and unsupported
                and SIGNIFICANCE_RE.search(window)
                and not NEGATED_SIGNIFICANCE_RE.search(window)
                and not HYPOTHESIS_RE.search(window)
            ):
                continue
            issues.append(
                _issue(
                    code="unsupported_factor1_pathway_significance",
                    file=path.name,
                    section=str(section["heading"]),
                    value=", ".join(unsupported),
                    evidence="sig_liana_pathway_factor.csv lacks Factor1 support for the claimed pathway(s).",
                    repair_instruction="Rephrase as an LR-annotation-based hypothesis, not measured pathway-factor significance.",
                )
            )


def _selected_lr_pairs(data_dir: Path) -> list[str]:
    data = _load_json(data_dir / "part4_candidate_selection.json")
    if not isinstance(data, dict):
        return []
    values: list[str] = []
    for row in data.get("selected_lr_pairs") or []:
        if not isinstance(row, dict):
            continue
        value = row.get("interaction") or row.get("lr_pair") or row.get("pair")
        if value:
            values.append(str(value))
    return values


def _mentions_lr_pair(text: str, pair: str) -> bool:
    if pair in text:
        return True
    ligand, sep, receptor = pair.partition("^")
    if not sep:
        return False
    return bool(re.search(rf"\b{re.escape(ligand)}\s*[-–/]\s*{re.escape(receptor)}\b", text))


def _check_part3_scope_and_pairs(data_dir: Path, issues: list[dict[str, str]]) -> None:
    path = data_dir / "part3_final.md"
    text = _read_text(path)
    if not text:
        return

    for section in _sections(text):
        body = str(section["body"])
        if THERAPEUTIC_RE.search(body):
            issues.append(
                _issue(
                    code="part3_therapeutic_spillover",
                    file=path.name,
                    section=str(section["heading"]),
                    value="therapeutic/druggability language",
                    evidence="Part3 should interpret selected L-R spatial evidence only; Part4 owns therapeutic synthesis.",
                    repair_instruction="Remove therapeutic prioritization language and keep the section to spatial/statistical LR evidence.",
                )
            )

    for pair in _selected_lr_pairs(data_dir):
        if not _mentions_lr_pair(text, pair):
            issues.append(
                _issue(
                    code="missing_selected_lr_pair",
                    file=path.name,
                    section="",
                    value=pair,
                    severity="warning",
                    evidence=f"{pair} is selected in part4_candidate_selection.json but not discussed in part3_final.md.",
                    repair_instruction="Add a concise evidence-grounded sentence for this selected LR pair if Part3 covers Figure 3-10/3-11.",
                )
            )


def validate_report(data_dir: Path) -> list[dict[str, str]]:
    data_dir = data_dir.resolve()
    issues: list[dict[str, str]] = []
    _check_pmids(data_dir, issues)
    _check_factor1_pathway_claims(data_dir, issues)
    _check_part3_scope_and_pairs(data_dir, issues)
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Deep Interpreter markdown reports.")
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    issues = validate_report(args.data_dir)
    payload = {"issue_count": len(issues), "issues": issues}
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 1 if any(i["severity"] == "error" for i in issues) else 0


if __name__ == "__main__":
    sys.exit(main())

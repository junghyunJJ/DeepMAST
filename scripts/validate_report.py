#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any


PMID_RE = re.compile(r"\bPMID[:\s]*(\d{6,9})\b", re.IGNORECASE)
SECTION_RE = re.compile(r"(^## .+?$)(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
THERAPEUTIC_RE = re.compile(
    r"\b(therapeutic|druggability|drug ranking|clinical prioritization|high-confidence therapeutic target)\b",
    re.IGNORECASE,
)
FACTOR_PATHWAY_POSITIVE_RE = re.compile(
    r"\b(enriched|enrichment|activation|activated|active|higher|increased|positive)\b",
    re.IGNORECASE,
)
FACTOR_PATHWAY_NEGATIVE_RE = re.compile(
    r"\b(depleted|depletion|negative|lower|reduced|attenuated|suppressed)\b",
    re.IGNORECASE,
)
FACTOR_PATHWAY_CLAIM_RE = re.compile(
    r"\b(significant|significantly|enriched|enrichment|activation|activated|active|higher|increased|positive|"
    r"depleted|depletion|negative|lower|reduced|attenuated|suppressed)\b",
    re.IGNORECASE,
)
FACTOR_RE = re.compile(r"\bFactor\s*\d+\b", re.IGNORECASE)
HYPOTHESIS_RE = re.compile(
    r"\b(may|might|could|hypothesis|inferred|suggests?|consistent with|not pathway-factor significance)\b",
    re.IGNORECASE,
)
NEGATED_SIGNIFICANCE_RE = re.compile(
    r"\b(?:no|not|without|lack|lacks|lacked|absent)\b.{0,40}\b(?:significant|significantly|"
    r"enriched|enrichment|activation|activated|active|higher|increased|positive|depleted|depletion|negative|"
    r"lower|reduced|attenuated|suppressed)\b|"
    r"\b(?:significant|significantly|enriched|enrichment|activation|activated|active|higher|increased|positive|"
    r"depleted|depletion|negative|lower|reduced|attenuated|suppressed)\b.{0,40}\b(?:no|not|without|lack|"
    r"lacks|lacked|absent)\b",
    re.IGNORECASE,
)
LR_METRIC_CLAIM_RE = re.compile(
    r"\b(?P<label>Moran's\s*R|combined\s*score|combinedscore|GenePT\s*score)\b"
    r"(?:\s+(?:score|value))?"
    r"\s*(?:=|:|of|is|was)?\s*\(?\s*"
    r"(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"\s*\)?",
    re.IGNORECASE,
)
LR_METRIC_COLUMNS = {
    "morans": ("morans", "moransR", "morans_r"),
    "combinedscore": ("combinedscore", "combined_rank_score"),
    "genept_score": ("genept_score", "genept"),
}


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


def _token_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _factor_key(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _factor_label(value: str) -> str:
    return re.sub(r"\s+", "", value.strip())


def _find_known_tokens(text: str, known: dict[str, str]) -> set[str]:
    found: set[str] = set()
    for key, label in known.items():
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(label)}(?![A-Za-z0-9])", text, re.IGNORECASE):
            found.add(key)
    return found


def _known_token_mentions(text: str, known: dict[str, str]) -> list[tuple[int, int, str]]:
    mentions: list[tuple[int, int, str]] = []
    for key, label in known.items():
        for match in re.finditer(rf"(?<![A-Za-z0-9]){re.escape(label)}(?![A-Za-z0-9])", text, re.IGNORECASE):
            mentions.append((match.start(), match.end(), key))
    return sorted(mentions)


def _find_known_factors(text: str, known: dict[str, str]) -> set[str]:
    found = _find_known_tokens(text, known)
    for match in FACTOR_RE.findall(text):
        key = _factor_key(match)
        if key in known:
            found.add(key)
    return found


def _claim_windows(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def _lr_pair_from_row(row: dict[str, str]) -> str:
    interaction = str(row.get("interaction") or "").strip()
    if interaction:
        return interaction
    ligand = str(row.get("ligand") or "").strip()
    receptor = str(row.get("receptor") or "").strip()
    return f"{ligand}^{receptor}" if ligand and receptor else ""


def _first_float(row: dict[str, str], columns: tuple[str, ...]) -> float | None:
    for column in columns:
        value = str(row.get(column) or "").strip()
        if value:
            try:
                return float(value)
            except ValueError:
                return None
    return None


def _sig_liana_metrics(data_dir: Path) -> dict[str, dict[str, float]]:
    path = data_dir / "sig_liana.csv"
    if not path.exists():
        return {}
    metrics: dict[str, dict[str, float]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pair = _lr_pair_from_row(row)
            if not pair:
                continue
            values = {
                metric: value
                for metric, columns in LR_METRIC_COLUMNS.items()
                if (value := _first_float(row, columns)) is not None
            }
            if values:
                metrics[pair] = values
    return metrics


def _lr_metric_from_label(label: str) -> str:
    key = _token_key(label)
    if key == "moransr":
        return "morans"
    if key == "geneptscore":
        return "genept_score"
    return "combinedscore"


def _lr_pair_pattern(pair: str) -> str:
    ligand, sep, receptor = pair.partition("^")
    if not sep:
        return rf"\b{re.escape(pair)}\b"
    return rf"\b{re.escape(ligand)}\s*(?:\^|[-–/])\s*{re.escape(receptor)}\b"


def _lr_pair_mentions(text: str, pairs: Iterable[str]) -> list[tuple[int, int, str]]:
    mentions: list[tuple[int, int, str]] = []
    for pair in pairs:
        for match in re.finditer(_lr_pair_pattern(str(pair)), text, re.IGNORECASE):
            mentions.append((match.start(), match.end(), str(pair)))
    return sorted(mentions)


def _check_lr_metric_claims(data_dir: Path, issues: list[dict[str, str]]) -> None:
    metrics = _sig_liana_metrics(data_dir)
    if not metrics:
        return
    path = data_dir / "part2_final.md"
    text = _read_text(path)
    if not text:
        return

    for section in _sections(text):
        for window in _claim_windows(str(section["body"])):
            pair_mentions = _lr_pair_mentions(window, metrics.keys())
            for index, (_, pair_end, pair) in enumerate(pair_mentions):
                phrase_end = pair_mentions[index + 1][0] if index + 1 < len(pair_mentions) else len(window)
                for claim in LR_METRIC_CLAIM_RE.finditer(window, pair_end, phrase_end):
                    metric = _lr_metric_from_label(claim.group("label"))
                    expected = metrics[pair].get(metric)
                    if expected is None:
                        continue
                    claimed_text = claim.group("value")
                    claimed = float(claimed_text)
                    if abs(claimed - expected) <= 0.001:
                        continue
                    issues.append(
                        _issue(
                            code="lr_metric_value_mismatch",
                            file=path.name,
                            section=str(section["heading"]),
                            value=f"{pair} {metric}={claimed_text}",
                            evidence=f"sig_liana.csv has {metric}={expected:.4f} for {pair}.",
                            repair_instruction="Use the metric value from sig_liana.csv or relabel the claim to the correct LR metric.",
                        )
                    )


def _supported_factor_pathways(data_dir: Path) -> tuple[dict[str, dict[str, float | None]], dict[str, str], dict[str, str]]:
    path = data_dir / "sig_liana_pathway_factor.csv"
    if not path.exists():
        return {}, {}, {}
    supported: dict[str, dict[str, float | None]] = {}
    factor_labels: dict[str, str] = {}
    pathway_labels: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            factor = str(row.get("factor") or row.get("Factor") or "")
            pathway = str(row.get("pathway") or row.get("Pathway") or "")
            if not factor.strip() or not pathway.strip():
                continue
            factor_key = _factor_key(factor)
            pathway_key = _token_key(pathway)
            supported.setdefault(factor_key, {})[pathway_key] = _first_float(row, ("estimate", "Estimate"))
            factor_labels.setdefault(factor_key, _factor_label(factor))
            pathway_labels.setdefault(pathway_key, pathway.strip())
    decoupler_path = data_dir / "sig_PathwayEnrich_decoupler.csv"
    if decoupler_path.exists():
        with decoupler_path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pathway = str(row.get("name") or row.get("pathway") or row.get("Pathway") or "")
                if pathway.strip():
                    pathway_labels.setdefault(_token_key(pathway), pathway.strip())
    return supported, factor_labels, pathway_labels


def _pathway_direction_claims(window: str, pathway_labels: dict[str, str]) -> dict[str, tuple[bool, bool]]:
    directions: dict[str, tuple[bool, bool]] = {}
    mentions = _known_token_mentions(window, pathway_labels)
    for index, (start, end, pathway) in enumerate(mentions):
        prev_end = mentions[index - 1][1] if index else 0
        next_start = mentions[index + 1][0] if index + 1 < len(mentions) else len(window)
        before = window[prev_end:start]
        after = window[end:next_start]
        local = after if FACTOR_PATHWAY_CLAIM_RE.search(after) else before
        if not FACTOR_PATHWAY_CLAIM_RE.search(local):
            local = window[prev_end:next_start]
        positive = bool(FACTOR_PATHWAY_POSITIVE_RE.search(local))
        negative = bool(FACTOR_PATHWAY_NEGATIVE_RE.search(local))
        old_positive, old_negative = directions.get(pathway, (False, False))
        directions[pathway] = (old_positive or positive, old_negative or negative)
    return directions


def _check_pathway_factor_claims(data_dir: Path, issues: list[dict[str, str]]) -> None:
    supported, factor_labels, pathway_labels = _supported_factor_pathways(data_dir)
    if not supported:
        return
    path = data_dir / "part2_final.md"
    text = _read_text(path)
    if not text:
        return
    for section in _sections(text):
        for window in _claim_windows(str(section["body"])):
            if not (
                FACTOR_PATHWAY_CLAIM_RE.search(window)
                and not NEGATED_SIGNIFICANCE_RE.search(window)
                and not HYPOTHESIS_RE.search(window)
            ):
                continue
            factors = _find_known_factors(window, factor_labels)
            pathways = _find_known_tokens(window, pathway_labels)
            pathway_directions = _pathway_direction_claims(window, pathway_labels)
            for factor in sorted(factors):
                factor_pathways = supported.get(factor, {})
                unsupported = sorted(pathways - set(factor_pathways))
                if unsupported:
                    issues.append(
                        _issue(
                            code="unsupported_pathway_factor_significance",
                            file=path.name,
                            section=str(section["heading"]),
                            value=", ".join(f"{factor_labels[factor]}: {pathway_labels[p]}" for p in unsupported),
                            evidence="sig_liana_pathway_factor.csv lacks the claimed factor-pathway support.",
                            repair_instruction="Rephrase as an LR-annotation-based hypothesis, not measured pathway-factor significance.",
                        )
                    )
                for pathway in sorted(pathways & set(factor_pathways)):
                    estimate = factor_pathways[pathway]
                    positive, negative = pathway_directions.get(pathway, (False, False))
                    if estimate is None:
                        continue
                    if (estimate < 0 and positive and not negative) or (estimate > 0 and negative and not positive):
                        issues.append(
                            _issue(
                                code="factor_pathway_direction_mismatch",
                                file=path.name,
                                section=str(section["heading"]),
                                value=f"{factor_labels[factor]}: {pathway_labels[pathway]} estimate={estimate}",
                                evidence="sig_liana_pathway_factor.csv estimate direction conflicts with the local factor-pathway wording.",
                                repair_instruction="Align enrichment/depletion wording with the estimate sign for this factor-pathway pair.",
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
    return bool(re.search(_lr_pair_pattern(pair), text))


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
    _check_lr_metric_claims(data_dir, issues)
    _check_pathway_factor_claims(data_dir, issues)
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

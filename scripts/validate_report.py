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
BIOLOGICAL_INTERPRETATION_RE = re.compile(
    r"^###\s+Biological Interpretation\s*$\n?(.*?)(?=^### |\Z)",
    re.MULTILINE | re.DOTALL,
)
THERAPEUTIC_RE = re.compile(
    r"\b(therapeutic|druggability|drug ranking|clinical prioritization|high-confidence therapeutic target)\b",
    re.IGNORECASE,
)
REPORT_EVIDENCE_RE = re.compile(
    r"\b(MISTy|Moran|co[-\s]?locali[zs]ation|spatial|Factor\s*\d+|FactorN|clusters?|importance|"
    r"z[-\s]?score|FDR|enrichment|NMF|LIANA|Decoupler|regions?)\b",
    re.IGNORECASE,
)
MECHANISTIC_TRIGGER_RE = re.compile(
    r"\b(confirms?|proves?|demonstrates?\s+that|drives?|driving|directly\s+causes?|"
    r"represents\s+a\s+fundamental\s+mechanism|would\s+be\s+particularly\s+sensitive\s+to|"
    r"therapy[-\s]+resistant\s+subpopulation|attempting\s+to\s+suppress|appears\s+compromised|"
    r"most\s+effective)\b",
    re.IGNORECASE,
)
MECHANISTIC_HEDGE_RE = re.compile(
    r"\b(may|might|could|suggests?|hypothesis|potential(?:ly)?|possibly|consistent with)\b",
    re.IGNORECASE,
)
FACTOR_PATHWAY_POSITIVE_RE = re.compile(
    r"\b(enriched|enrichment|activation|activated|active|higher|increased|positive(?:ly)?)\b",
    re.IGNORECASE,
)
FACTOR_PATHWAY_NEGATIVE_RE = re.compile(
    r"\b(depleted|depletion|negative(?:ly)?|inverse(?:ly)?|lower|reduced|attenuated|suppressed)\b",
    re.IGNORECASE,
)
FACTOR_PATHWAY_NEGATED_DIRECTION_RE = re.compile(
    r"\b(?:no|not|without|lack|lacks|lacked|absent)\b(?:\s+\w+){0,2}\s+"
    r"\b(?:enriched|enrichment|activation|activated|active|higher|increased|positive(?:ly)?|"
    r"depleted|depletion|negative(?:ly)?|inverse(?:ly)?|lower|reduced|attenuated|suppressed)\b",
    re.IGNORECASE,
)
FACTOR_CLUSTER_STATUS_RE = re.compile(
    r"\bFactor\s*\d+\s+(?:is\s+)?(?:enriched|higher|increased|active)\s+"
    r"in\s+clusters?\b(?:\s+\d+)*(?:\s+and\s+\d+)?(?:\s+\([^)]*loadings[^)]*\))?",
    re.IGNORECASE,
)
FACTOR_PATHWAY_CLAIM_RE = re.compile(
    r"\b(significant|significantly|enriched|enrichment|activation|activated|active|higher|increased|positive(?:ly)?|"
    r"depleted|depletion|negative(?:ly)?|inverse(?:ly)?|lower|reduced|attenuated|suppressed)\b",
    re.IGNORECASE,
)
FACTOR_PATHWAY_CONNECTOR_RE = re.compile(r"\b(?:and|but|while|whereas)\b", re.IGNORECASE)
FACTOR_RE = re.compile(r"\bFactor\s*\d+\b", re.IGNORECASE)
HYPOTHESIS_RE = re.compile(
    r"\b(may|might|could|hypothes(?:is|i[sz]ed)|hypothetical|inferred|suggests?|consistent with|"
    r"not pathway-factor significance)\b",
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
    r"\b(?P<label>Moran(?:'s|s)?\s*[RI]|combined\s*score|combinedscore|GenePT\s*score)\b"
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
    target_text: str = "",
    replacement_text: str = "",
) -> dict[str, str]:
    issue = {
        "code": code,
        "severity": severity,
        "file": file,
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


def _known_factor_mentions(text: str, known: dict[str, str]) -> list[tuple[int, int, str]]:
    mentions = _known_token_mentions(text, known)
    for match in FACTOR_RE.finditer(text):
        key = _factor_key(match.group(0))
        if key in known:
            mentions.append((match.start(), match.end(), key))
    return sorted(set(mentions))


def _claim_windows(text: str) -> list[str]:
    chunks: list[str] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            chunks.append("\n".join(paragraph).strip())
            paragraph.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            continue
        if re.match(r"^(?:#{1,6}\s|[-*+]\s|\d+[.)]\s)", line):
            flush_paragraph()
            chunks.append(line)
            continue
        paragraph.append(line)
    flush_paragraph()

    windows: list[str] = []
    for chunk in chunks:
        windows.extend(
            part.strip()
            for part in re.split(r"(?<=[.!?])(?:[ \t]+|\n+)(?=\S)", chunk)
            if part.strip()
        )
    return windows


def _biological_interpretation_blocks(section_body: str) -> list[str]:
    return [match.group(1) for match in BIOLOGICAL_INTERPRETATION_RE.finditer(section_body)]


def _check_mechanistic_interpretations(data_dir: Path, issues: list[dict[str, str]]) -> None:
    for path in sorted(data_dir.glob("part*_final.md")):
        text = _read_text(path)
        if not text:
            continue
        for section in _sections(text):
            for block in _biological_interpretation_blocks(str(section["body"])):
                for window in _claim_windows(block):
                    if not (REPORT_EVIDENCE_RE.search(window) and MECHANISTIC_TRIGGER_RE.search(window)):
                        continue
                    warning = bool(MECHANISTIC_HEDGE_RE.search(window))
                    issues.append(
                        _issue(
                            code=(
                                "mechanistic_interpretation_warning"
                                if warning
                                else "unsupported_mechanistic_interpretation"
                            ),
                            file=path.name,
                            section=str(section["heading"]),
                            value=window,
                            severity="warning" if warning else "error",
                            evidence="Report-derived spatial/statistical evidence was written as a mechanistic or causal claim.",
                            repair_instruction=(
                                "Rewrite as an association or hypothesis unless direct experimental evidence is cited "
                                "for this exact report-derived claim."
                            ),
                            target_text="" if warning else window,
                        )
                    )


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
    if key in {"moranr", "moransr", "morani", "moransi"}:
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

    for path in sorted(data_dir.glob("part*_final.md")):
        text = _read_text(path)
        if not text:
            continue
        for section in _sections(text):
            for window in _claim_windows(str(section["body"])):
                pair_mentions = _lr_pair_mentions(window, metrics.keys())
                for index, (pair_start, pair_end, pair) in enumerate(pair_mentions):
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
                        target_text = window[pair_start : claim.end("value")]
                        value_start = claim.start("value") - pair_start
                        value_end = claim.end("value") - pair_start
                        issues.append(
                            _issue(
                                code="lr_metric_value_mismatch",
                                file=path.name,
                                section=str(section["heading"]),
                                value=f"{pair} {metric}={claimed_text}",
                                evidence=f"sig_liana.csv has {metric}={expected:.4f} for {pair}.",
                                repair_instruction="Use the metric value from sig_liana.csv or relabel the claim to the correct LR metric.",
                                target_text=target_text,
                                replacement_text=(
                                    f"{target_text[:value_start]}{expected:.4f}"
                                    f"{target_text[value_end:]}"
                                ),
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


def _direction_flags(text: str) -> tuple[bool, bool]:
    text = FACTOR_CLUSTER_STATUS_RE.sub("", text)
    text = FACTOR_PATHWAY_NEGATED_DIRECTION_RE.sub("", text)
    return bool(FACTOR_PATHWAY_POSITIVE_RE.search(text)), bool(FACTOR_PATHWAY_NEGATIVE_RE.search(text))


def _split_direction_gap(text: str) -> tuple[str, str]:
    matches = list(FACTOR_PATHWAY_CONNECTOR_RE.finditer(text))
    if not matches:
        return text, ""
    match = matches[-1]
    return text[: match.start()], text[match.end() :]


def _pathway_direction_claims(window: str, pathway_labels: dict[str, str]) -> dict[str, tuple[bool, bool]]:
    directions: dict[str, tuple[bool, bool]] = {}
    mentions = _known_token_mentions(window, pathway_labels)
    if not mentions:
        return directions

    gaps: list[tuple[str, str, bool]] = []
    for index in range(len(mentions) - 1):
        gap = window[mentions[index][1] : mentions[index + 1][0]]
        left, right = _split_direction_gap(gap)
        positive, negative = _direction_flags(f"{left} {right}")
        gaps.append((left, right, positive or negative))

    group_start = 0
    for index, (_, _, has_direction) in enumerate(gaps):
        if not has_direction:
            continue
        _add_pathway_group_directions(window, mentions, gaps, group_start, index, directions)
        group_start = index + 1
    _add_pathway_group_directions(window, mentions, gaps, group_start, len(mentions) - 1, directions)
    return directions


def _local_factor_pathway_windows(
    window: str,
    factor_labels: dict[str, str],
    pathway_labels: dict[str, str],
) -> dict[str, tuple[str, set[str]]]:
    chunks: dict[str, list[tuple[str, set[str]]]] = {}
    context_factors: set[str] = set()
    context_text = ""
    for clause in re.finditer(r"[^,;]+", window):
        text = clause.group(0)
        factor_mentions = _known_factor_mentions(text, factor_labels)
        pathway_mentions = _known_token_mentions(text, pathway_labels)
        factors = {factor for _, _, factor in factor_mentions}
        pathways = {pathway for _, _, pathway in pathway_mentions}
        if factors:
            context_factors = factors
            context_text = text
        if pathways and not factors and context_factors:
            for factor in context_factors:
                chunks.setdefault(factor, []).append((f"{context_text} {text}", pathways))
            continue
        if not factors or not pathways:
            continue
        if len(factors) == 1:
            chunks.setdefault(next(iter(factors)), []).append((text, pathways))
            continue
        if len(pathways) == 1:
            for factor in factors:
                chunks.setdefault(factor, []).append((text, pathways))
            continue
        for pathway_start, pathway_end, pathway in pathway_mentions:
            factor = min(
                factor_mentions,
                key=lambda mention: min(abs(pathway_start - mention[1]), abs(mention[0] - pathway_end)),
            )[2]
            chunks.setdefault(factor, []).append((text, {pathway}))

    return {
        factor: (" ".join(text for text, _ in parts), set().union(*(pathways for _, pathways in parts)))
        for factor, parts in chunks.items()
    }


def _add_pathway_group_directions(
    window: str,
    mentions: list[tuple[int, int, str]],
    gaps: list[tuple[str, str, bool]],
    group_start: int,
    group_end: int,
    directions: dict[str, tuple[bool, bool]],
) -> None:
    prefix = window[: mentions[0][0]] if group_start == 0 else gaps[group_start - 1][1]
    suffix = window[mentions[-1][1] :] if group_end == len(mentions) - 1 else gaps[group_end][0]
    prefix_positive, prefix_negative = _direction_flags(prefix)
    suffix_positive, suffix_negative = _direction_flags(suffix)
    positive = prefix_positive or suffix_positive
    negative = prefix_negative or suffix_negative
    for index in range(group_start, group_end + 1):
        pathway = mentions[index][2]
        old_positive, old_negative = directions.get(pathway, (False, False))
        directions[pathway] = (old_positive or positive, old_negative or negative)


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
            if not (FACTOR_PATHWAY_CLAIM_RE.search(window) and not HYPOTHESIS_RE.search(window)):
                continue
            local_windows = _local_factor_pathway_windows(window, factor_labels, pathway_labels)
            for factor, (local_window, pathways) in sorted(local_windows.items()):
                factor_pathways = supported.get(factor, {})
                pathway_directions = _pathway_direction_claims(local_window, pathway_labels)
                unsupported = sorted(pathways - set(factor_pathways))
                if unsupported and not NEGATED_SIGNIFICANCE_RE.search(local_window):
                    issues.append(
                        _issue(
                            code="unsupported_pathway_factor_significance",
                            file=path.name,
                            section=str(section["heading"]),
                            value=", ".join(f"{factor_labels[factor]}: {pathway_labels[p]}" for p in unsupported),
                            evidence="sig_liana_pathway_factor.csv lacks the claimed factor-pathway support.",
                            repair_instruction="Rephrase as an LR-annotation-based hypothesis, not measured pathway-factor significance.",
                            target_text=window,
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
                                target_text=window,
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
        for window in _claim_windows(body):
            if THERAPEUTIC_RE.search(window):
                issues.append(
                    _issue(
                        code="part3_therapeutic_spillover",
                        file=path.name,
                        section=str(section["heading"]),
                        value=window,
                        evidence="Part3 should interpret selected L-R spatial evidence only; Part4 owns therapeutic synthesis.",
                        repair_instruction="Remove therapeutic prioritization language and keep the section to spatial/statistical LR evidence.",
                        target_text=window,
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
    _check_mechanistic_interpretations(data_dir, issues)
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

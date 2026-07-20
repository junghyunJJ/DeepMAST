from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_SYNTHESIS_CANDIDATE_RE = re.compile(
    r"^###\s+(?P<rank>\d+)\.\s+(?P<gene>[A-Za-z0-9_-]+)\s+"
    r"\(Combined Score:\s*(?P<score>-?\d+(?:\.\d+)?)\)",
    re.MULTILINE,
)
_SOURCE_CANDIDATE_RE = re.compile(
    r"^###\s+(?P<rank>\d+)\.\s+Candidate:\s+(?P<gene>[A-Za-z0-9_-]+)\s*$"
    r"(?P<body>.*?)(?=^###\s+\d+\.|\Z)",
    re.MULTILINE | re.DOTALL,
)
_COMBINED_RE = re.compile(r"\bcombined\s+(?P<score>-?\d+(?:\.\d+)?)\b", re.IGNORECASE)
_LR_RE = re.compile(
    r"\b(?P<pair>[A-Za-z0-9]+[-^][A-Za-z0-9]+)\s+combinedscore\s*=\s*"
    r"(?P<value>-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_QUANT_RE = re.compile(
    r"^(?P<label>[A-Za-z][A-Za-z0-9 _/-]*?[A-Za-z0-9])\s*=\s*"
    r"(?P<value>-?\d+(?:\.\d+)?)\.",
    re.MULTILINE,
)
_QUANT_SECTION_RE = re.compile(
    r"^###\s+Quantitative Findings\s*$"
    r"(?P<body>.*?)(?=^###\s+|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)


def validate_synthesis_consistency(data_dir: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Return deterministic consistency issues and provenance results for synthesis.md."""
    data_dir = Path(data_dir).expanduser().resolve()
    synthesis = _read_text(data_dir / "synthesis.md")
    if synthesis is None:
        return {"issues": [], "results": []}

    issues: list[dict[str, Any]] = []
    canonical: dict[str, dict[str, str]] = {}
    part4_payload = _load_part4_selection(data_dir, issues)
    has_part4_selection = part4_payload is not None
    if has_part4_selection:
        for gene in part4_payload.get("selected_genes", []):
            canonical[f"gene:{str(gene).upper()}"] = {
                "source_file": "part4_candidate_selection.json",
                "kind": "candidate",
                "canonical_value": str(gene),
            }
        for pair in part4_payload.get("selected_lr_pairs", []):
            if not isinstance(pair, dict):
                continue
            interaction = pair.get("interaction")
            score = pair.get("combinedscore")
            if interaction is None or score is None:
                continue
            canonical[f"lr:{_normalize_lr(str(interaction))}"] = {
                "source_file": "part4_candidate_selection.json",
                "kind": "lr_combinedscore",
                "canonical_value": _format_json_number(score),
                "source_pair": str(interaction),
            }

    for gene, fact in _extract_candidate_scores(data_dir).items():
        canonical[f"candidate_score:{gene}"] = fact
    canonical.update(_extract_quantitative_facts(data_dir))

    results: list[dict[str, Any]] = []
    for match in _SYNTHESIS_CANDIDATE_RE.finditer(synthesis):
        if not has_part4_selection:
            continue
        rank = match.group("rank")
        gene = match.group("gene").upper()
        score = match.group("score")
        selected = canonical.get(f"gene:{gene}")
        score_fact = canonical.get(f"candidate_score:{gene}")
        if selected is None or score_fact is None:
            _add_issue(
                issues,
                code="synthesis_consistency_unresolved",
                value=match.group("gene"),
                replacement="",
                repairable=False,
            )
            continue
        results.append(
            _result(
                score_fact,
                observed_value=score,
                status="match" if score == score_fact["canonical_value"] else "mismatch",
                repairable=_can_repair(synthesis, score),
            )
        )
        if rank != score_fact["rank"]:
            _add_issue(
                issues,
                code="synthesis_consistency_candidate_mismatch",
                value=rank,
                replacement=score_fact["rank"],
                repairable=_can_repair(synthesis, rank),
            )
        if score != score_fact["canonical_value"]:
            _add_issue(
                issues,
                code="synthesis_consistency_score_mismatch",
                value=score,
                replacement=score_fact["canonical_value"],
                repairable=_can_repair(synthesis, score),
            )

    for match in _LR_RE.finditer(synthesis):
        if not has_part4_selection:
            continue
        key = f"lr:{_normalize_lr(match.group('pair'))}"
        fact = canonical.get(key)
        value = match.group("value")
        if fact is None:
            _add_issue(
                issues,
                code="synthesis_consistency_unresolved",
                value=match.group("pair"),
                replacement="",
                repairable=False,
            )
            continue
        replacement = fact["canonical_value"]
        results.append(
            _result(
                fact,
                observed_value=value,
                status="match" if value == replacement else "mismatch",
                repairable=_can_repair(synthesis, value),
            )
        )
        if value != replacement:
            _add_issue(
                issues,
                code="synthesis_consistency_lr_mismatch",
                value=value,
                replacement=replacement,
                repairable=_can_repair(synthesis, value),
            )

    for match in _QUANT_RE.finditer(synthesis):
        key = f"quant:{_normalize_label(match.group('label'))}"
        fact = canonical.get(key)
        if fact is None:
            continue
        value = match.group("value")
        replacement = fact["canonical_value"]
        results.append(
            _result(
                fact,
                observed_value=value,
                status="match" if value == replacement else "mismatch",
                repairable=_can_repair(synthesis, value),
            )
        )
        if value != replacement:
            _add_issue(
                issues,
                code="synthesis_consistency_quantitative_mismatch",
                value=value,
                replacement=replacement,
                repairable=_can_repair(synthesis, value),
            )

    return {"issues": issues, "results": results}


def repair_synthesis_consistency(
    data_dir: str | Path, issues: list[dict[str, str]]
) -> int:
    """Replace only issue values with their exact canonical replacements."""
    path = Path(data_dir).expanduser().resolve() / "synthesis.md"
    current = path.read_text(encoding="utf-8")
    changed = 0
    cursor = 0
    for issue in issues:
        if not issue.get("repairable"):
            continue
        value = issue.get("value") or ""
        replacement = issue.get("replacement") or ""
        if not value or not replacement:
            continue
        at = current.find(value, cursor)
        if at < 0:
            continue
        current = current[:at] + replacement + current[at + len(value) :]
        cursor = at + len(replacement)
        changed += 1
    if changed:
        path.write_text(current, encoding="utf-8")
    return changed


def _load_part4_selection(
    data_dir: Path, issues: list[dict[str, Any]]
) -> dict[str, Any] | None:
    path = data_dir / "part4_candidate_selection.json"
    if not path.exists():
        issues.append(
            {
                "code": "synthesis_consistency_source_missing",
                "severity": "warning",
                "file": path.name,
                "value": path.name,
                "repairable": False,
            }
        )
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        issues.append(
            {
                "code": "synthesis_consistency_source_malformed",
                "severity": "warning",
                "file": path.name,
                "value": path.name,
                "repairable": False,
            }
        )
        return None


def _extract_candidate_scores(data_dir: Path) -> dict[str, dict[str, str]]:
    text = _read_text(data_dir / "part4_therapeutic_synthesis.md") or ""
    facts: dict[str, dict[str, str]] = {}
    for match in _SOURCE_CANDIDATE_RE.finditer(text):
        score = _COMBINED_RE.search(match.group("body"))
        if not score:
            continue
        gene = match.group("gene").upper()
        facts[gene] = {
            "source_file": "part4_therapeutic_synthesis.md",
            "kind": "candidate_score",
            "canonical_value": score.group("score"),
            "rank": match.group("rank"),
        }
    return facts


def _extract_quantitative_facts(data_dir: Path) -> dict[str, dict[str, str]]:
    facts: dict[str, dict[str, str]] = {}
    for name in ("part1_final.md", "part2_final.md", "part3_final.md"):
        text = _read_text(data_dir / name) or ""
        for section in _QUANT_SECTION_RE.finditer(text):
            for match in _QUANT_RE.finditer(section.group("body")):
                facts[f"quant:{_normalize_label(match.group('label'))}"] = {
                    "source_file": name,
                    "kind": "quantitative",
                    "canonical_value": match.group("value"),
                }
    return facts


def _add_issue(
    issues: list[dict[str, Any]],
    *,
    code: str,
    value: str,
    replacement: str,
    repairable: bool,
) -> None:
    issues.append(
        {
            "code": code,
            "severity": "error",
            "file": "synthesis.md",
            "value": value,
            "replacement": replacement,
            "observed_value": value,
            "canonical_value": replacement,
            "repairable": repairable,
        }
    )


def _result(
    fact: dict[str, str],
    *,
    observed_value: str,
    status: str,
    repairable: bool,
) -> dict[str, Any]:
    return {
        "source_file": fact["source_file"],
        "kind": fact["kind"],
        "canonical_value": fact["canonical_value"],
        "observed_value": observed_value,
        "status": status,
        "repairable": repairable,
    }


def _normalize_lr(value: str) -> str:
    return value.replace("^", "-").upper()


def _normalize_label(value: str) -> str:
    return " ".join(value.lower().split())


def _can_repair(text: str, value: str) -> bool:
    return bool(value) and text.count(value) == 1


def _format_json_number(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")

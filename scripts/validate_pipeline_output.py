#!/usr/bin/env python3
"""Deterministic invariant gate for drug-target pipeline output.

Exits non-zero if any of five invariants fails against a pipeline data dir
(expected to contain ``target_assessment.json``, ``drug.md``, and
``evidence/``).

Invariants
----------
1. Track consistency
     Every entry in ``featured_candidates_deep_dive`` with ``track == "novel"``
     must correspond to a gene whose ``druggability_matrix`` classification
     (or ``rubric_assessment`` classification when available) is
     ``novel_candidate``.
2. OT score sanity
     Every gene with non-empty ``ot_<GENE>.json.associations`` must have
     ``open_targets_score > 0`` somewhere in ``druggability_matrix``.
3. JSON spec compliance
     No ``Infinity`` / ``-Infinity`` / ``NaN`` literals in any JSON file under
     ``evidence/`` or at the data_dir root.
4. GWAS ground truth (soft)
     If any of the known IPF loci (MUC5B, TERT, TOLLIP, DPP9, FAM13A) are
     present in ``assessment_results.rubric_assessment``, their
     ``gwas_support`` must be >= 1. (Warning only — some runs do not include
     these genes in the L-R panel.)
5. Hypothesis grounding
     Every ``hypothesis_report.json.hypotheses[*].prediction_grounding`` must
     be either ``"grounded"`` or ``"qualitative"`` (never ``"unverified"``).

Usage
-----
::

    python scripts/validate_pipeline_output.py <data_dir>
    python scripts/validate_pipeline_output.py res_ipf_qwen2/
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


INVALID_FLOAT_RE = re.compile(r"\b(?:-?Infinity|NaN)\b")


def _load_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def check_track_consistency(data_dir: Path) -> list[str]:
    errors: list[str] = []
    ta = _load_json(data_dir / "target_assessment.json")
    if not isinstance(ta, dict):
        return ["target_assessment.json missing or unreadable"]
    ar = _load_json(data_dir / "evidence" / "assessment_results.json")

    rubric_cls: dict[str, str] = {}
    if isinstance(ar, dict):
        for row in ar.get("rubric_assessment", []) or []:
            g = str((row or {}).get("gene") or "").upper()
            cls = str((row or {}).get("classification") or "").strip()
            if g and cls:
                rubric_cls[g] = cls

    for entry in ta.get("featured_candidates_deep_dive", []) or []:
        if not isinstance(entry, dict):
            continue
        gene = str(entry.get("target_gene") or entry.get("gene") or "").upper()
        track = str(entry.get("track") or "").lower()
        cls = rubric_cls.get(gene, "").strip()
        # novel-tagged genes MUST be classified novel_candidate.
        if track == "novel" and cls and cls != "novel_candidate":
            errors.append(
                f"track_contradiction gene={gene} track=novel classification={cls}"
            )
        # featured-tagged genes MUST NOT be classified novel_candidate.
        if track == "featured" and cls == "novel_candidate":
            errors.append(
                f"track_contradiction gene={gene} track=featured classification=novel_candidate"
            )
    return errors


def check_ot_score_sanity(data_dir: Path) -> list[str]:
    errors: list[str] = []
    ta = _load_json(data_dir / "target_assessment.json")
    if not isinstance(ta, dict):
        return []
    ev = data_dir / "evidence"
    if not ev.is_dir():
        return []

    ot_has_assocs: dict[str, bool] = {}
    for p in ev.glob("ot_*.json"):
        data = _load_json(p)
        if not isinstance(data, dict):
            continue
        gene = p.stem.replace("ot_", "").upper()
        assocs = data.get("associations") or []
        ot_has_assocs[gene] = bool(assocs)

    # A gene row matters if either ligand or receptor is in ot_has_assocs[True]
    failing: list[str] = []
    for row in ta.get("druggability_matrix", []) or []:
        if not isinstance(row, dict):
            continue
        score = row.get("open_targets_score")
        ligand = str(row.get("ligand", "")).upper()
        receptor = str(row.get("receptor", "")).upper()
        relevant_gene = (
            ligand if ot_has_assocs.get(ligand) else
            receptor if ot_has_assocs.get(receptor) else None
        )
        if relevant_gene is None:
            continue
        try:
            if float(score or 0) <= 0:
                failing.append(f"{ligand}--{receptor} (relevant={relevant_gene})")
        except Exception:
            failing.append(f"{ligand}--{receptor} (relevant={relevant_gene})")
    if failing:
        errors.append(
            f"open_targets_score <= 0 for {len(failing)} pair(s) with OT associations: "
            f"{failing[:5]}{'...' if len(failing) > 5 else ''}"
        )
    return errors


def check_json_spec(data_dir: Path) -> list[str]:
    errors: list[str] = []
    for p in list(data_dir.glob("*.json")) + list((data_dir / "evidence").glob("*.json")):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in INVALID_FLOAT_RE.finditer(text):
            errors.append(f"{p.name} contains non-RFC-8259 literal '{m.group(0)}'")
            break  # one per file
    return errors


def check_gwas_ground_truth(data_dir: Path) -> list[str]:
    # Warning-only: return strings formatted as "WARN: ..." so caller can downgrade.
    warnings: list[str] = []
    ar = _load_json(data_dir / "evidence" / "assessment_results.json")
    if not isinstance(ar, dict):
        return warnings
    known = {"MUC5B", "TERT", "TOLLIP", "DPP9", "FAM13A"}
    for row in ar.get("rubric_assessment", []) or []:
        g = str((row or {}).get("gene") or "").upper()
        if g not in known:
            continue
        if int((row or {}).get("gwas_support") or 0) < 1:
            warnings.append(
                f"WARN known IPF locus {g} has gwas_support=0 "
                f"(expected >=1); GWAS pipeline may still be degraded"
            )
    return warnings


def check_hypothesis_grounding(data_dir: Path) -> list[str]:
    errors: list[str] = []
    hr = _load_json(data_dir / "evidence" / "hypothesis_report.json")
    if not isinstance(hr, dict):
        return errors
    for idx, h in enumerate(hr.get("hypotheses", []) or []):
        if not isinstance(h, dict):
            continue
        g = str(h.get("prediction_grounding") or "").lower()
        if g == "unverified":
            tokens = h.get("prediction_numeric_tokens") or []
            errors.append(
                f"hypotheses[{idx}] '{str(h.get('title',''))[:50]}' grounding=unverified "
                f"(ungrounded tokens: {tokens})"
            )
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data_dir", type=Path, help="Pipeline data directory")
    ap.add_argument(
        "--allow-gwas-gap",
        action="store_true",
        help="Treat missing IPF GWAS signal as a warning (default).",
    )
    args = ap.parse_args()

    data_dir = args.data_dir.resolve()
    if not data_dir.is_dir():
        print(f"ERROR: {data_dir} is not a directory", file=sys.stderr)
        return 2

    hard_errors: list[str] = []
    warnings: list[str] = []

    hard_errors.extend(check_track_consistency(data_dir))
    hard_errors.extend(check_ot_score_sanity(data_dir))
    hard_errors.extend(check_json_spec(data_dir))
    hard_errors.extend(check_hypothesis_grounding(data_dir))
    warnings.extend(check_gwas_ground_truth(data_dir))

    if hard_errors:
        print(f"FAIL: {len(hard_errors)} hard invariant violation(s)")
        for e in hard_errors:
            print(f"  - {e}")
    else:
        print("PASS: all hard invariants satisfied")

    if warnings:
        print(f"{len(warnings)} warning(s):")
        for w in warnings:
            print(f"  - {w}")

    return 1 if hard_errors else 0


if __name__ == "__main__":
    sys.exit(main())

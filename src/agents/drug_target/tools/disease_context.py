"""Disease-context metadata helpers for drug-target evidence stages."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "drug-target-disease-context-v1"


def normalize_disease_label(value: Any) -> str:
    """Normalize disease labels for equality checks without changing display text."""
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def disease_labels_equal(left: Any, right: Any) -> bool:
    """Return True when two disease labels are the same after whitespace/case folding."""
    left_norm = normalize_disease_label(left)
    right_norm = normalize_disease_label(right)
    return bool(left_norm and left_norm == right_norm)


def disease_context_path(evidence_dir: str | Path) -> Path:
    return Path(evidence_dir) / "disease_context.json"


def load_disease_context(evidence_dir: str | Path) -> dict[str, Any]:
    """Load disease_context.json if present and well-formed."""
    path = disease_context_path(evidence_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def initialize_disease_context(
    evidence_dir: str | Path,
    *,
    input_disease: str,
    input_source: str = "",
) -> dict[str, Any]:
    """Create or update the root disease context without stage-specific metadata."""
    return merge_disease_context(
        evidence_dir,
        input_disease=input_disease,
        input_source=input_source,
    )


def merge_disease_context(
    evidence_dir: str | Path,
    *,
    input_disease: str | None = None,
    input_source: str | None = None,
    stage1: dict[str, Any] | None = None,
    stage2: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge disease-context metadata and persist it atomically enough for local runs."""
    out_dir = Path(evidence_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    current = load_disease_context(out_dir)

    context: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": datetime.now().isoformat(),
        "input_disease": str(input_disease or current.get("input_disease") or "").strip(),
        "canonical_disease": str(input_disease or current.get("canonical_disease") or "").strip(),
    }
    if input_source or current.get("input_source"):
        context["input_source"] = input_source or current.get("input_source")

    if isinstance(current.get("stage1"), dict):
        context["stage1"] = current["stage1"]
    if isinstance(current.get("stage2"), dict):
        context["stage2"] = current["stage2"]
    if stage1 is not None:
        context["stage1"] = stage1
    if stage2 is not None:
        context["stage2"] = stage2

    warnings: list[str] = []
    stage1_meta = context.get("stage1")
    stage2_meta = context.get("stage2")
    if isinstance(stage1_meta, dict) and stage1_meta.get("fallback_used"):
        warnings.append(
            "Stage1 used a Census-compatible fallback disease label: "
            f"{stage1_meta.get('disease_used')!r}."
        )
    if isinstance(stage2_meta, dict) and stage2_meta.get("fallback_used"):
        warnings.append(
            "Stage2 used an OpenTargets fallback disease label: "
            f"{stage2_meta.get('match_label') or stage2_meta.get('disease_used')!r}."
        )
    if isinstance(stage1_meta, dict) and isinstance(stage2_meta, dict):
        stage1_disease = stage1_meta.get("disease_used")
        stage2_disease = stage2_meta.get("disease_used")
        if stage1_disease and stage2_disease and not disease_labels_equal(stage1_disease, stage2_disease):
            warnings.append(
                "Stage1 and Stage2 used different backend disease labels: "
                f"Stage1={stage1_disease!r}, Stage2={stage2_disease!r}."
            )
    if warnings:
        context["warnings"] = warnings

    path = disease_context_path(out_dir)
    path.write_text(json.dumps(context, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return context


def resolve_stage2_input_disease(
    evidence_dir: str | Path,
    requested_disease: str,
) -> tuple[str, str | None]:
    """Prefer the Phase-0 input disease over an LLM-supplied Stage2 fallback label."""
    context = load_disease_context(evidence_dir)
    input_disease = str(context.get("input_disease") or "").strip()
    requested = str(requested_disease or "").strip()
    if input_disease and requested and not disease_labels_equal(input_disease, requested):
        return (
            input_disease,
            f"Stage2 disease argument {requested!r} overridden by input disease {input_disease!r}.",
        )
    return requested or input_disease, None


def select_exact_or_first_disease_hit(
    hits: list[dict[str, Any]] | None,
    requested_disease: str,
) -> tuple[dict[str, Any] | None, bool]:
    """Pick an exact disease-name hit when available; otherwise return the top hit."""
    hits = [hit for hit in (hits or []) if isinstance(hit, dict)]
    requested_norm = normalize_disease_label(requested_disease)
    if requested_norm:
        for hit in hits:
            for key in ("name", "label"):
                if normalize_disease_label(hit.get(key)) == requested_norm:
                    return hit, True
    return (hits[0], False) if hits else (None, False)


def compact_ot_disease_context(context: dict[str, Any] | None) -> dict[str, Any]:
    """Return the non-bulky OpenTargets disease metadata for artifacts."""
    context = context or {}
    return {
        "requested_disease": context.get("disease"),
        "disease_used": context.get("disease"),
        "efo_id": context.get("efo_id"),
        "match_label": context.get("match_label"),
        "exact_match": bool(context.get("exact_match", False)),
        "fallback_used": bool(context.get("fallback_used", False)),
        "fallback_reason": context.get("fallback_reason", ""),
        "source": "OpenTargets",
    }

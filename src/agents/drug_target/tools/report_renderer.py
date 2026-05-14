"""Deterministic drug.md renderer from structured report expansion artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from src.agents.drug_target.tools.report_expansion_schema import (
    build_expansion_slots,
    canonical_json_hash,
    validate_report_expansions,
)

_EXPAND_RE = re.compile(r"<!--\s*EXPAND(?:_SLOT)?:\s*(.*?)\s*-->", re.DOTALL)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _slot_text(slot: dict) -> str:
    sentences = slot.get("sentences", [])
    return "\n".join(
        str(sentence.get("text", "")).strip()
        for sentence in sentences
        if isinstance(sentence, dict) and str(sentence.get("text", "")).strip()
    )


def _inject_expansion_slots(template: str, required_slots: list[str], slot_map: dict[str, dict]) -> str:
    slot_iter = iter(required_slots)

    def repl(_: re.Match) -> str:
        slot_id = next(slot_iter)
        return _slot_text(slot_map[slot_id])

    return _EXPAND_RE.sub(repl, template)


def _label_hypothesis_headings(markdown: str, hypothesis_data: dict) -> str:
    hyps = hypothesis_data.get("hypotheses") if isinstance(hypothesis_data, dict) else None
    if not isinstance(hyps, list):
        return markdown
    title_to_label: dict[str, str] = {}
    for hyp in hyps:
        if not isinstance(hyp, dict):
            continue
        title = str(hyp.get("title") or "").strip()
        gap_type = hyp.get("gap_type")
        if title and gap_type == "featured_coverage":
            title_to_label[title] = "[FEATURED-GAP]"
        elif title and gap_type == "orphan_evidence":
            title_to_label[title] = "[GAP]"
    for title, label in title_to_label.items():
        markdown = re.sub(
            rf"(###\s+4\.\d+\.\s+)(?!\[)(%s)" % re.escape(title),
            rf"\1{label} \2",
            markdown,
        )
    return markdown


def render_drug_md(data_dir: str | Path) -> dict:
    base = Path(data_dir).expanduser().resolve()
    ref_path = base / "drug_report_reference_card.json"
    exp_path = base / "report_expansions.json"
    hyp_path = base / "evidence" / "hypothesis_report.json"
    if not ref_path.exists() or not exp_path.exists():
        return {
            "rendered": False,
            "errors": ["drug_report_reference_card.json and report_expansions.json are required"],
        }
    expansions = _load_json(exp_path)
    reference_card, errors = validate_report_expansions(base, expansions)
    if errors or reference_card is None:
        return {"rendered": False, "errors": errors}

    required_slots = [
        str(slot.get("slot_id"))
        for slot in reference_card.get("expansion_slots", [])
        if isinstance(slot, dict) and slot.get("slot_id")
    ] or [
        slot["slot_id"]
        for slot in build_expansion_slots(reference_card)
    ]
    slot_map = {
        slot["slot_id"]: slot
        for slot in expansions.get("slots", [])
        if isinstance(slot, dict) and slot.get("slot_id")
    }
    markdown = _inject_expansion_slots(
        reference_card.get("markdown_template", ""),
        required_slots,
        slot_map,
    )
    markdown = _label_hypothesis_headings(
        markdown,
        reference_card.get("hypothesis_data", {}),
    )
    markdown = markdown.rstrip() + "\n"
    drug_md_path = base / "drug.md"
    drug_md_path.write_text(markdown, encoding="utf-8")

    hypothesis_hash = None
    if hyp_path.exists():
        hypothesis_hash = canonical_json_hash(_load_json(hyp_path))
    source_hashes = {
        "reference_card": canonical_json_hash(reference_card),
        "report_expansions": canonical_json_hash(expansions),
        "hypothesis_report": hypothesis_hash,
        "template": _sha256_text(reference_card.get("markdown_template", "")),
    }
    metadata = {
        "schema_version": "drug_report_render.v1",
        "renderer": "render_drug_md_from_expansions",
        "mode": "renderer",
        "source_paths": {
            "reference_card": str(ref_path),
            "report_expansions": str(exp_path),
            "hypothesis_report": str(hyp_path) if hyp_path.exists() else None,
            "template": "drug_report_reference_card.json:markdown_template",
        },
        "source_hashes": source_hashes,
        "rendered_drug_md_sha256": _sha256_text(markdown),
        "required_slot_count": len(required_slots),
        "rendered_slot_count": len(slot_map),
        "missing_slots": sorted(set(required_slots) - set(slot_map)),
        "extra_slots": sorted(set(slot_map) - set(required_slots)),
        "pagination_warnings": reference_card.get("pagination_warnings", []),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    metadata_path = base / "drug_report_render.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "rendered": True,
        "path": str(drug_md_path),
        "metadata_path": str(metadata_path),
        "rendered_drug_md_sha256": metadata["rendered_drug_md_sha256"],
    }


@tool
def render_drug_md_from_expansions(data_dir: str) -> str:
    """Render drug.md deterministically from Reference Card and expansions."""
    return json.dumps(render_drug_md(data_dir), indent=2)

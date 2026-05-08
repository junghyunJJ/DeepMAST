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
_PAIR_CONTEXT_RE = re.compile(
    r"^\s*-\s+\*\*(?P<pair>[^*]+?)\*\*:\s*STRING\s+PPI\s+score=",
    re.IGNORECASE,
)
_UNCITED_CENSUS_RE = re.compile(
    r"^(?P<body>\s*-\s+Census:\s*risk_ratio=(?P<rr>[^,\n]+),\s*p_value=(?P<pval>[^\s\[]+))"
    r"(?:\s+\((?P<note>[^][]*)\))?$",
    re.IGNORECASE,
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _slot_section(slot: dict) -> str:
    section = str(slot.get("section_id") or slot.get("section") or "").strip()
    if section:
        return section
    slot_id = str(slot.get("slot_id") or "")
    for part in slot_id.split("|"):
        if part.startswith("section:"):
            return part.split(":", 1)[1]
    return ""


def _is_hypothesis_slot(slot: dict) -> bool:
    return _slot_section(slot) in {"hypothesis", "hypothesis_summary"}


def _is_conservative_reference_fallback(text: str) -> bool:
    lowered = text.casefold()
    return (
        "summarized conservatively from the current reference card" in lowered
        and "evidence-limited local context" in lowered
    )


def _slot_text(slot: dict) -> str:
    sentences = slot.get("sentences", [])
    return "\n".join(
        _sentence_text(sentence, slot=slot)
        for sentence in sentences
        if isinstance(sentence, dict) and _sentence_text(sentence, slot=slot)
    )


def _annotation_field(sentence: dict) -> str:
    provenance = sentence.get("source_provenance")
    if isinstance(provenance, dict):
        field = str(provenance.get("source_field") or "").strip()
        if field:
            return re.sub(r"[^A-Za-z0-9_]+", "_", field).strip("_").lower()
    source_fields = sentence.get("source_fields")
    if isinstance(source_fields, list):
        for field in source_fields:
            text = str(field or "").strip()
            if text:
                text = text.rsplit(".", 1)[-1]
                return re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_").lower()
    return "interpretation"


def _sentence_text(sentence: dict, *, slot: dict | None = None) -> str:
    text = str(sentence.get("text", "")).strip()
    if not text:
        return ""
    if slot is not None and _is_hypothesis_slot(slot) and _is_conservative_reference_fallback(text):
        return ""
    text = re.sub(r"\s*\[source:\s*[^\]]+\]", "", text, flags=re.IGNORECASE).strip()
    return f"{text} [source: {_annotation_field(sentence)}]"


def _inject_expansion_slots(template: str, required_slots: list[str], slot_map: dict[str, dict]) -> str:
    slot_iter = iter(required_slots)

    def repl(_: re.Match) -> str:
        slot_id = next(slot_iter)
        return _slot_text(slot_map[slot_id])

    return _EXPAND_RE.sub(repl, template)


def _disease_scope_note(reference_card: dict) -> str:
    scope = reference_card.get("disease_scope")
    if not isinstance(scope, dict) or scope.get("requires_proxy_note") is not True:
        return ""
    note = str(scope.get("proxy_note") or "").strip()
    if not note:
        return ""
    if "[source:" not in note.casefold():
        note = f"{note} [source: disease_scope]"
    return note


def _insert_disease_scope_note(markdown: str, reference_card: dict) -> str:
    note = _disease_scope_note(reference_card)
    if not note or note in markdown:
        return markdown
    heading_re = re.compile(r"(##\s+4\.\s+Hypothesis-Driven Analysis\s*\n+)")
    if not heading_re.search(markdown):
        return markdown
    return heading_re.sub(rf"\1{note}\n\n", markdown, count=1)


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


def _split_stage1_pair(pair: str) -> tuple[str, str] | None:
    for sep in ("–", "—", "--"):
        if sep in pair:
            ligand, receptor = pair.split(sep, 1)
            ligand = ligand.strip()
            receptor = receptor.strip()
            if ligand and receptor:
                return ligand, receptor
    return None


def _low_rr_direction_note(risk_ratio: str) -> str:
    try:
        value = float(risk_ratio)
    except (TypeError, ValueError):
        return ""
    if value < 1:
        return "direction=lower_target_vs_rest; RR<1 is not enrichment"
    return ""


def _cite_stage1_census_lines(markdown: str, evidence_dir: Path) -> str:
    lines = markdown.splitlines()
    current_pair: tuple[str, str] | None = None
    cited: list[str] = []
    for line in lines:
        pair_match = _PAIR_CONTEXT_RE.match(line)
        if pair_match:
            current_pair = _split_stage1_pair(pair_match.group("pair"))
            cited.append(line)
            continue
        census_match = _UNCITED_CENSUS_RE.match(line)
        if (
            current_pair is not None
            and census_match
            and ".json" not in line.casefold()
            and "[from " not in line.casefold()
        ):
            ligand, receptor = current_pair
            source_name = f"stage1_{ligand}--{receptor}.json"
            if (evidence_dir / source_name).exists():
                note = str(census_match.group("note") or "")
                direction_note = _low_rr_direction_note(str(census_match.group("rr") or ""))
                if direction_note and not note:
                    line = f"{census_match.group('body')} ({direction_note})"
                line = f"{line} [from {source_name}]"
        cited.append(line)
    trailing_newline = "\n" if markdown.endswith("\n") else ""
    return "\n".join(cited) + trailing_newline


def _drop_empty_gap_analysis(markdown: str) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    idx = 0
    heading_re = re.compile(r"^(#{1,6})\s+(.+?)\s*:?\s*$")
    while idx < len(lines):
        match = heading_re.match(lines[idx].strip())
        if not match or len(match.group(1)) != 3 or match.group(2).strip() != "Gap Analysis":
            output.append(lines[idx])
            idx += 1
            continue
        depth = len(match.group(1))
        block: list[str] = []
        scan = idx + 1
        while scan < len(lines):
            next_match = heading_re.match(lines[scan].strip())
            if next_match and len(next_match.group(1)) <= depth:
                break
            block.append(lines[scan])
            scan += 1
        if len(re.sub(r"\s+", "", "\n".join(block))) >= 20:
            output.append(lines[idx])
            output.extend(block)
        idx = scan
    trailing_newline = "\n" if markdown.endswith("\n") else ""
    return "\n".join(output) + trailing_newline


def render_drug_md(data_dir: str | Path) -> dict:
    base = Path(data_dir).expanduser().resolve()
    ref_path = base / "drug_report_reference_card.json"
    exp_path = base / "report_expansions.json"
    default_hyp_path = base / "evidence" / "hypothesis_report.json"
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
    markdown = _insert_disease_scope_note(markdown, reference_card)
    markdown = _label_hypothesis_headings(
        markdown,
        reference_card.get("hypothesis_data", {}),
    )
    markdown = _cite_stage1_census_lines(markdown, base / "evidence")
    markdown = _drop_empty_gap_analysis(markdown)
    markdown = markdown.rstrip() + "\n"
    drug_md_path = base / "drug.md"
    drug_md_path.write_text(markdown, encoding="utf-8")

    hypothesis_hash = None
    hypothesis_source = reference_card.get("hypothesis_source")
    hyp_path = default_hyp_path
    if isinstance(hypothesis_source, dict) and hypothesis_source.get("path"):
        candidate = base / str(hypothesis_source["path"])
        if candidate.exists():
            hyp_path = candidate
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

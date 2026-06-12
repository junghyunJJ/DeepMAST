"""HTML report generator for Drug Target Assessment Reports.

Parses drug.md into structured sections and renders via Jinja2 template.
CSS/JS loaded from skills/html-report-generator/assets/ (same theme as CCI reports).
Produces self-contained HTML with embedded styles.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, BaseLoader
from langchain_core.tools import tool

from src.agents.drug_target.tools.evidence_loader import _resolve_data_dir
from src.agents.drug_target.tools.scoring_metadata import NOVELTY_OPPORTUNITY_LEGEND

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_ASSETS_DIR = _PROJECT_ROOT / "skills" / "html-report-generator" / "assets"
_TEMPLATE_DIR = _PROJECT_ROOT / "skills" / "drug-target-reporting" / "templates"


# ---------------------------------------------------------------------------
# Markdown parser — top-level
# ---------------------------------------------------------------------------

def parse_drug_md(md_text: str) -> dict[str, Any]:
    """Parse drug.md into a structured context dict for Jinja2 rendering.

    Returns dict with keys: title, disease, executive_summary, matrix,
    deep_dives, pipeline_summary.
    """
    # Strip EXPAND markers globally
    cleaned = re.sub(r"<!--\s*EXPAND:.*?-->", "", md_text)

    # Split into top-level sections on ## headers
    sections = re.split(r"^## ", cleaned, flags=re.MULTILINE)
    # sections[0] = everything before first ##  (title area)
    # sections[1..] = "1. Executive Summary\n...", "2. Druggability Matrix\n...", etc.

    title, disease = _parse_title(sections[0])

    context: dict[str, Any] = {
        "title": title,
        "disease": disease,
        "executive_summary": {"text": "", "featured_candidates": []},
        "matrix": {"headers": [], "rows": [], "legend": {}},
        "deep_dives": [],
        "hypothesis": [],
        "primary_hypotheses": [],
        "secondary_hypotheses": [],
        "gene_level_hypotheses": [],
        "unbucketed_hypotheses": [],
        "secondary_stage1_framing_pairs": [],
        "pipeline_summary": {},
    }

    for sec in sections[1:]:
        header_line = sec.split("\n", 1)[0].strip()
        body = sec.split("\n", 1)[1] if "\n" in sec else ""

        if header_line.startswith("1."):
            context["executive_summary"] = _parse_executive_summary(body)
        elif header_line.startswith("2."):
            context["matrix"] = _parse_druggability_matrix(body)
        elif header_line.startswith("3."):
            context["deep_dives"] = _parse_deep_dives(body)
        elif header_line.startswith("4.") and (
            "Hypothesis" in header_line or "Follow-up" in header_line
        ):
            context["hypothesis"] = _parse_hypothesis_section(body)
            context["primary_hypotheses"] = [
                h
                for h in context["hypothesis"]
                if h.get("_tier") == "primary_epithelial_intrinsic"
            ]
            context["secondary_hypotheses"] = [
                h
                for h in context["hypothesis"]
                if h.get("_tier") == "secondary_epithelial_associated_niche"
            ]
            context["gene_level_hypotheses"] = [
                h
                for h in context["hypothesis"]
                if h.get("_tier") == "gene_level_actionability"
            ]
            context["unbucketed_hypotheses"] = [
                h for h in context["hypothesis"] if not h.get("_tier")
            ]
            context["secondary_stage1_framing_pairs"] = (
                _parse_secondary_stage1_framing_pairs(body)
            )
        elif header_line.startswith("4."):
            context["pipeline_summary"] = _parse_pipeline_summary(body)
        elif header_line.startswith("5."):
            context["pipeline_summary"] = _parse_pipeline_summary(body)

    # Fallback: if no matrix rows but deep dives have rubric data, build rows
    if not context["matrix"]["rows"] and context["deep_dives"]:
        context["matrix"] = _build_matrix_from_deep_dives(context["deep_dives"])

    # Fallback: enrich featured candidates from deep dives if missing classification
    candidates = context["executive_summary"]["featured_candidates"]
    if candidates and not candidates[0].get("classification"):
        dive_lookup = {d["gene"]: d for d in context["deep_dives"]}
        for c in candidates:
            dive = dive_lookup.get(c["gene"], {})
            c["classification"] = c.get("classification") or dive.get("classification", "validated_target")
            c["priority"] = c.get("priority") or dive.get("priority", "high")
            if not c["combined_total"] and dive.get("rubric", {}).get("combined_total"):
                c["combined_total"] = dive["rubric"]["combined_total"]
            if not c["exploratory_total"] and dive.get("rubric", {}).get("exploratory_total"):
                c["exploratory_total"] = dive["rubric"]["exploratory_total"]

    return context


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------

def _parse_title(preamble: str) -> tuple[str, str]:
    """Extract report title and disease from the H1 line.

    Handles both formats:
      # Therapeutic Target Assessment Report — pulmonary fibrosis
      # Therapeutic Target Assessment: Idiopathic Pulmonary Fibrosis
    """
    # Try dash-separated first
    m = re.search(r"^#\s+(.+?)\s*[—–-]\s*(.+)$", preamble, re.MULTILINE)
    if m:
        title = m.group(1).strip()
        disease = m.group(2).strip()
        return f"{title} — {disease}", disease

    # Try colon-separated (e.g. "Assessment: Idiopathic Pulmonary Fibrosis")
    m = re.search(r"^#\s+(.+?):\s*(.+)$", preamble, re.MULTILINE)
    if m:
        title = m.group(1).strip()
        disease = m.group(2).strip()
        return f"{title} — {disease}", disease

    # Fallback: just grab the whole H1 line
    m = re.search(r"^#\s+(.+)$", preamble, re.MULTILINE)
    if m:
        return m.group(1).strip(), ""
    return "Therapeutic Target Assessment Report", ""


def _parse_executive_summary(body: str) -> dict[str, Any]:
    """Parse executive summary text and featured candidates list.

    Handles multiple formats:
      Format A: - **CD4** — Classification: validated_target, Priority: high, Combined Total: 16
      Format B: - **CD4** (Combined=16)
      Format C: - **CD4** (16)
    """
    # Split at ### Featured Candidates (if present)
    parts = re.split(r"^###\s+Featured Candidates", body, flags=re.MULTILINE)
    candidate_text = parts[1] if len(parts) > 1 else body
    summary_text = _md_to_html(parts[0].strip()) if parts else _md_to_html(body.strip())

    candidates: list[dict] = []

    # Format A: full structured format
    for m in re.finditer(
        r"-\s+\*\*(\S+)\*\*\s*—\s*Classification:\s*(\w+),\s*Priority:\s*(\w+)"
        r"(?:,\s*Exploratory Total:\s*(\d+))?"
        r"(?:,\s*Combined Total:\s*(\d+))?",
        candidate_text,
    ):
        candidates.append({
            "gene": m.group(1),
            "classification": m.group(2),
            "priority": m.group(3),
            "exploratory_total": int(m.group(4)) if m.group(4) else 0,
            "combined_total": int(m.group(5)) if m.group(5) else 0,
        })

    # Format B/C: short format  - **CD4** (Combined=16) or - **CD4** (16)
    if not candidates:
        for m in re.finditer(
            r"-\s+\*\*(\S+)\*\*\s*\((?:Combined=)?(\d+)\)",
            candidate_text,
        ):
            candidates.append({
                "gene": m.group(1),
                "classification": "",
                "priority": "",
                "exploratory_total": 0,
                "combined_total": int(m.group(2)),
            })

    return {"text": summary_text, "featured_candidates": candidates}


def _parse_druggability_matrix(body: str) -> dict[str, Any]:
    """Parse the pipe-delimited druggability table and scoring legend."""
    lines = body.strip().split("\n")

    # Find table lines (start with |)
    table_lines = [l for l in lines if l.strip().startswith("|")]
    headers: list[str] = []
    rows: list[dict[str, Any]] = []

    if len(table_lines) >= 2:
        # Header row
        raw_headers = [c.strip() for c in table_lines[0].split("|")[1:-1]]
        headers = raw_headers

        # Skip separator row (table_lines[1])
        for row_line in table_lines[2:]:
            cells = [c.strip() for c in row_line.split("|")[1:-1]]
            if len(cells) < len(headers):
                continue

            gene_raw = cells[0]
            is_featured = "**" in gene_raw
            gene = gene_raw.replace("**", "").strip()

            has_rank_score = len(cells) > 11 and headers[11].strip().lower() == "rank score"
            classification_idx = 12 if has_rank_score else 11
            priority_idx = 13 if has_rank_score else 12
            stage3_idx = 14 if has_rank_score else 13

            row: dict[str, Any] = {
                "gene": gene,
                "is_featured": is_featured,
                "existing_drug_evidence": _safe_int(cells[1]),
                "clinical_trial_activity": _safe_int(cells[2]),
                "safety_profile": _safe_int(cells[3]),
                "validated_total": _safe_int(cells[4]),
                "gwas_support": _safe_int(cells[5]),
                "tractability": _safe_int(cells[6]),
                "biological_plausibility": _safe_int(cells[7]),
                "novelty_opportunity": _safe_int(cells[8]),
                "exploratory_total": _safe_int(cells[9]),
                "combined_total": _safe_int(cells[10]),
                "combined_rank_score": _safe_float(cells[11]) if has_rank_score else _safe_int(cells[10]),
                "classification": cells[classification_idx].strip() if len(cells) > classification_idx else "",
                "priority": cells[priority_idx].strip() if len(cells) > priority_idx else "",
                "stage3": cells[stage3_idx].strip().lower() == "yes" if len(cells) > stage3_idx else False,
            }
            rows.append(row)

    # Parse scoring legend (everything after the table)
    legend = _parse_scoring_legend(body)

    return {"headers": headers, "rows": rows, "legend": legend}


def _parse_scoring_legend(body: str) -> dict[str, Any]:
    """Parse the Scoring Legend section with validated/exploratory track tables."""
    legend: dict[str, Any] = {}

    # Split on #### or ##### headers for track sub-sections
    track_sections = re.split(r"^#{4,5}\s+", body, flags=re.MULTILINE)
    for sec in track_sections:
        header = sec.split("\n", 1)[0].strip().lower()
        sec_body = sec.split("\n", 1)[1] if "\n" in sec else ""

        if "validated" in header:
            legend["validated_track"] = _parse_legend_table(sec_body)
        elif "exploratory" in header:
            legend["exploratory_track"] = _parse_legend_table(sec_body)
        elif "combined" in header:
            legend["combined_section"] = _parse_legend_table(sec_body)

    return legend


def _parse_legend_table(body: str) -> list[dict[str, str]]:
    """Parse a pipe-delimited legend table into list of row dicts."""
    lines = [l for l in body.strip().split("\n") if l.strip().startswith("|")]
    if len(lines) < 3:
        return []

    headers = [c.strip() for c in lines[0].split("|")[1:-1]]
    rows: list[dict[str, str]] = []
    for line in lines[2:]:
        cells = [c.strip() for c in line.split("|")[1:-1]]
        row = {}
        for i, h in enumerate(headers):
            row[h] = cells[i] if i < len(cells) else ""
        rows.append(row)
    return rows


def _build_matrix_from_deep_dives(deep_dives: list[dict]) -> dict[str, Any]:
    """Build a matrix from deep dive rubric data when no pipe table exists."""
    headers = [
        "Gene", "Drug Ev.", "Trial", "Safety", "Val. Total",
        "GWAS", "Tract.", "Bio. Plaus.", "Novelty", "Expl. Total",
        "Combined", "Rank Score", "Classification", "Priority", "Stage3",
    ]
    rows: list[dict[str, Any]] = []
    for dive in deep_dives:
        rubric = dive.get("rubric", {})
        rows.append({
            "gene": dive["gene"],
            "is_featured": True,
            "existing_drug_evidence": rubric.get("existing_drug_evidence", 0),
            "clinical_trial_activity": rubric.get("clinical_trial_activity", 0),
            "safety_profile": rubric.get("safety_profile", 0),
            "validated_total": rubric.get("validated_total", 0),
            "gwas_support": rubric.get("gwas_support", 0),
            "tractability": rubric.get("tractability", 0),
            "biological_plausibility": rubric.get("biological_plausibility", 0),
            "novelty_opportunity": rubric.get("novelty_opportunity", 0),
            "exploratory_total": rubric.get("exploratory_total", 0),
            "combined_total": rubric.get("combined_total", 0),
            "combined_rank_score": rubric.get("combined_rank_score", rubric.get("combined_total", 0)),
            "classification": dive.get("classification", ""),
            "priority": dive.get("priority", ""),
            "stage3": True,
        })
    return {"headers": headers, "rows": rows, "legend": {}}


def _parse_deep_dives(body: str) -> list[dict[str, Any]]:
    """Parse section 3 into per-gene deep dive structures."""
    # Split on ### GENE — Classification: ...
    gene_sections = re.split(r"^### ", body, flags=re.MULTILINE)
    dives: list[dict[str, Any]] = []

    for sec in gene_sections:
        if not sec.strip():
            continue

        # Parse gene header: "CD4 — Classification: validated_target | Priority: high"
        header_m = re.match(
            r"(\S+)\s*—\s*Classification:\s*(\S+)\s*\|\s*Priority:\s*(\S+)",
            sec.split("\n", 1)[0],
        )
        if not header_m:
            continue

        gene = header_m.group(1)
        classification = header_m.group(2)
        priority = header_m.group(3)

        # Split into sub-sections on **A. ... **, **B. ... **, etc.
        dive: dict[str, Any] = {
            "gene": gene,
            "classification": classification,
            "priority": priority,
            "drug_profile": {"clinical_drugs": [], "preclinical_compounds": []},
            "biological_context": [],
            "rubric": {},
            "narrative": {},
        }

        # Find sub-section boundaries
        sub_parts = re.split(r"\*\*([A-D])\.\s+(.+?)\*\*", sec)
        # sub_parts alternates: [pre, letter, title, body, letter, title, body, ...]
        i = 1
        while i + 2 < len(sub_parts):
            letter = sub_parts[i]
            sub_body = sub_parts[i + 2]
            if letter == "A":
                dive["drug_profile"] = _parse_drug_profile(sub_body)
            elif letter == "B":
                dive["biological_context"] = _parse_bio_context(sub_body)
            elif letter == "C":
                dive["rubric"] = _parse_rubric_assessment(sub_body)
            elif letter == "D":
                dive["rubric"] = _parse_rubric_assessment(sub_body)  # legacy
            i += 3

        dives.append(dive)

    return dives


def _parse_drug_profile(body: str) -> dict[str, Any]:
    """Parse drug profile entries into clinical and preclinical lists."""
    clinical: list[dict[str, str]] = []
    preclinical: list[dict[str, str]] = []

    for m in re.finditer(
        r"-\s+\*\*(.+?)\*\*\s+\(ChEMBL:\s*(CHEMBL\d+)\)\s*—\s*(.+?),"
        r"\s*Max Phase:\s*(.+?)(?:,\s*Indications:\s*(.+))?$",
        body,
        re.MULTILINE,
    ):
        drug = {
            "name": m.group(1),
            "chembl_id": m.group(2),
            "mechanism": m.group(3).strip(),
            "max_phase": m.group(4).strip(),
            "indications": m.group(5).strip() if m.group(5) else "N/A",
        }
        if drug["max_phase"].lower() == "preclinical" or drug["indications"] == "N/A":
            preclinical.append(drug)
        else:
            clinical.append(drug)

    return {"clinical_drugs": clinical, "preclinical_compounds": preclinical}


def _parse_bio_context(body: str) -> list[dict[str, Any]]:
    """Parse biological context entries (STRING + Census)."""
    pairs: list[dict[str, Any]] = []

    # Match: - **HLA-DPA1–CD4**: STRING PPI score=0.977, interaction=confirmed
    for m in re.finditer(
        r"-\s+\*\*(.+?)\*\*:\s*STRING PPI score=([\d.]+),\s*interaction=(\S+)",
        body,
    ):
        pair: dict[str, Any] = {
            "pair": m.group(1),
            "string_score": float(m.group(2)),
            "interaction": m.group(3),
            "census_risk_ratio": "",
            "census_p_value": "",
        }
        # Look for Census sub-line after this match
        remaining = body[m.end():]
        census_m = re.match(
            r"\s*\n\s+-\s+Census:\s*risk_ratio=([\S]+),\s*p_value=([\S]+)",
            remaining,
        )
        if census_m:
            pair["census_risk_ratio"] = census_m.group(1)
            pair["census_p_value"] = census_m.group(2)
        pairs.append(pair)

    return pairs


def _parse_rubric_assessment(body: str) -> dict[str, Any]:
    """Parse rubric assessment lines into structured dict."""
    rubric: dict[str, Any] = {}

    # Validated Track line
    vt_m = re.search(
        r"Validated Track:\s*existing_drug_evidence=(-?\d+),\s*"
        r"clinical_trial_activity=(-?\d+),\s*safety_profile=(-?\d+)"
        r"\s*→\s*\*\*validated_total=(-?\d+)\*\*",
        body,
    )
    if vt_m:
        rubric["existing_drug_evidence"] = int(vt_m.group(1))
        rubric["clinical_trial_activity"] = int(vt_m.group(2))
        rubric["safety_profile"] = int(vt_m.group(3))
        rubric["validated_total"] = int(vt_m.group(4))

    # Exploratory Track line
    et_m = re.search(
        r"Exploratory Track:\s*gwas_support=(-?\d+),\s*"
        r"tractability=(-?\d+),\s*biological_plausibility=(-?\d+),\s*"
        r"novelty_opportunity=(-?\d+)\s*→\s*\*\*exploratory_total=(-?\d+)\*\*",
        body,
    )
    if et_m:
        rubric["gwas_support"] = int(et_m.group(1))
        rubric["tractability"] = int(et_m.group(2))
        rubric["biological_plausibility"] = int(et_m.group(3))
        rubric["novelty_opportunity"] = int(et_m.group(4))
        rubric["exploratory_total"] = int(et_m.group(5))

    # GWAS Audit line
    gwas_audit_m = re.search(
        r"GWAS Audit:\s*evidence_type=([^,\n]*),\s*"
        r"min_pvalue=([^,\n]*),\s*"
        r"trait_match=([^,\n]*),\s*"
        r"direct_hits=([^,\n]*),\s*"
        r"proximity_hits=([^\n]*)",
        body,
    )
    if gwas_audit_m:
        min_pvalue = gwas_audit_m.group(2).strip()
        rubric["gwas_evidence_type"] = gwas_audit_m.group(1).strip()
        rubric["gwas_min_pvalue"] = _safe_optional_float(min_pvalue)
        rubric["gwas_trait_match_level"] = gwas_audit_m.group(3).strip()
        rubric["gwas_direct_hit_count"] = _safe_int(gwas_audit_m.group(4))
        rubric["gwas_proximity_hit_count"] = _safe_int(gwas_audit_m.group(5))

    # Biological Audit line
    biological_audit_m = re.search(
        r"Biological Audit:\s*basis=([^,\n]*),\s*"
        r"evidence_types=([^,\n]*),\s*"
        r"evidence_count=([^,\n]*),\s*"
        r"max_ot_score=([^,\n]*),\s*"
        r"vep_high_impact_count=([^,\n]*),\s*"
        r"stage1_pair_count=([^,\n]*),\s*"
        r"stage1_pairs=([^\n]*)",
        body,
    )
    if biological_audit_m:
        max_ot_score = biological_audit_m.group(4).strip()
        rubric["biological_basis"] = biological_audit_m.group(1).strip()
        rubric["biological_evidence_types"] = biological_audit_m.group(2).strip()
        rubric["biological_evidence_count"] = _safe_int(biological_audit_m.group(3))
        rubric["biological_max_ot_score"] = _safe_optional_float(max_ot_score)
        rubric["vep_high_impact_count"] = _safe_int(biological_audit_m.group(5))
        rubric["stage1_support_pair_count"] = _safe_int(biological_audit_m.group(6))
        rubric["stage1_support_pairs"] = biological_audit_m.group(7).strip()

    # Stage1 Audit line
    stage1_audit_m = re.search(
        r"Stage1 Audit:\s*gate_status=([^,\n]*),\s*"
        r"total_pairs=([^,\n]*),\s*"
        r"passed_pairs=([^,\n]*),\s*"
        r"failed_pairs=([^,\n]*),\s*"
        r"best_pair=([^,\n]*),\s*"
        r"best_string=([^,\n]*),\s*"
        r"best_coexpr_p=([^,\n]*),\s*"
        r"best_gene_a_p=([^,\n]*),\s*"
        r"best_gene_b_p=([^,\n]*),\s*"
        r"source=([^\n]*)",
        body,
    )
    if stage1_audit_m:
        rubric["stage1_gate_status"] = stage1_audit_m.group(1).strip()
        rubric["stage1_total_pair_count"] = _safe_int(stage1_audit_m.group(2))
        rubric["stage1_passed_pair_count"] = _safe_int(stage1_audit_m.group(3))
        rubric["stage1_failed_pair_count"] = _safe_int(stage1_audit_m.group(4))
        rubric["stage1_best_pair"] = stage1_audit_m.group(5).strip()
        rubric["stage1_best_string_combined"] = _safe_optional_float(stage1_audit_m.group(6).strip())
        rubric["stage1_best_coexpr_pvalue"] = _safe_optional_float(stage1_audit_m.group(7).strip())
        rubric["stage1_best_gene_a_pvalue"] = _safe_optional_float(stage1_audit_m.group(8).strip())
        rubric["stage1_best_gene_b_pvalue"] = _safe_optional_float(stage1_audit_m.group(9).strip())
        rubric["stage1_source"] = stage1_audit_m.group(10).strip()

    # Novelty Audit line
    novelty_audit_m = re.search(
        r"Novelty Audit:\s*basis=([^,\n]*),\s*"
        r"association_count=([^,\n]*),\s*"
        r"target_drug_count=([^,\n]*),\s*"
        r"bucket=([^,\n]*),\s*"
        r"source=([^\n]*)",
        body,
    )
    if novelty_audit_m:
        rubric["novelty_basis"] = novelty_audit_m.group(1).strip()
        rubric["novelty_association_count"] = _safe_int(novelty_audit_m.group(2))
        rubric["novelty_target_drug_count"] = _safe_int(novelty_audit_m.group(3))
        rubric["novelty_bucket"] = novelty_audit_m.group(4).strip()
        rubric["novelty_source"] = novelty_audit_m.group(5).strip()

    # Audit Metadata line
    audit_m = re.search(
        r"Audit Metadata:\s*tractability_basis=([^,\n]*),\s*"
        r"tractability_modalities=([^,\n]*),\s*"
        r"tractability_evidence_label=([^,\n]*),\s*"
        r"safety_evidence_level=([^,\n]*),\s*"
        r"safety_liability_count=([^,\n]*),\s*"
        r"safety_liability_sources=([^\n]*)",
        body,
    )
    if audit_m:
        rubric["tractability_basis"] = audit_m.group(1).strip()
        rubric["tractability_modalities"] = audit_m.group(2).strip()
        rubric["tractability_evidence_label"] = audit_m.group(3).strip()
        rubric["safety_evidence_level"] = audit_m.group(4).strip()
        rubric["safety_liability_count"] = _safe_int(audit_m.group(5))
        rubric["safety_liability_sources"] = audit_m.group(6).strip()

    # Combined Total line
    ct_m = re.search(
        r"\*\*Combined Total:\s*(-?\d+)\*\*\s*\|\s*Classification:\s*(\S+)\s*\|\s*Priority:\s*(\S+)",
        body,
    )
    if ct_m:
        rubric["combined_total"] = int(ct_m.group(1))
        rubric["classification"] = ct_m.group(2)
        rubric["priority"] = ct_m.group(3)

    return rubric


def _parse_hypothesis_section(body: str) -> list[dict[str, Any]]:
    """Parse section 4 follow-up recommendation entries into a structured list."""
    hypotheses: list[dict[str, Any]] = []

    # New reports render individual entries as #### 4.1.1.; retain a fallback
    # for older reports that used ### 4.N. entry headings.
    if re.search(
        r"^#### \d+\.\d+(?:\.\d+)?\.\s+",
        body,
        flags=re.MULTILINE,
    ):
        h_sections = re.split(
            r"^#### \d+\.\d+(?:\.\d+)?\.\s+",
            body,
            flags=re.MULTILINE,
        )
    else:
        h_sections = re.split(r"^### \d+\.\d+\.\s+", body, flags=re.MULTILINE)

    for i, sec in enumerate(h_sections):
        if not sec.strip() or i == 0:
            continue  # skip preamble before first ###

        lines = sec.strip()
        title = lines.split("\n", 1)[0].strip()
        source_heading = re.search(
            rf"^####\s+(\d+\.(?P<tier>[123])\.(?P<tier_rank>\d+))\.\s+{re.escape(title)}\s*$",
            body,
            flags=re.MULTILINE,
        )
        tier = ""
        tier_label = ""
        if source_heading:
            if source_heading.group("tier") == "1":
                tier = "primary_epithelial_intrinsic"
                tier_label = "Primary epithelial/AT2-intrinsic"
            elif source_heading.group("tier") == "2":
                tier = "secondary_epithelial_associated_niche"
                tier_label = "Secondary epithelial-associated niche"
            elif source_heading.group("tier") == "3":
                tier = "gene_level_actionability"
                tier_label = "Gene-level/actionability follow-up"

        category_m = re.search(r"\*\*Category:\*\*\s*(.+)", lines)
        tier_label_m = re.search(r"\*\*Interpretation Tier:\*\*\s*(.+)", lines)
        claim_m = re.search(
            r"\*\*(?:Core Claim|Conservative Interpretation):\*\*\s*(.+)", lines
        )
        biological_grounding_m = re.search(r"\*\*Biological Grounding:\*\*\s*(.+)", lines)
        target_disease_support_m = re.search(
            r"\*\*Target-Disease Support:\*\*\s*(.+)", lines
        )
        actionability_m = re.search(r"\*\*Actionability:\*\*\s*(.+)", lines)
        interpretation_constraint_m = re.search(
            r"\*\*Interpretation Constraint:\*\*\s*(.+)", lines
        )
        prediction_m = re.search(
            r"\*\*(?:Falsifiable Prediction|Recommended Follow-up Test):\*\*\s*(.+)",
            lines,
        )
        validation_m = re.search(
            r"\*\*(?:Validation Approach|Suggested Validation Approach):\*\*\s*(.+)",
            lines,
        )

        # Parse biological entities
        genes: list[str] = []
        pathways: list[str] = []
        cell_types: list[str] = []
        drugs: list[str] = []

        genes_m = re.search(r"-\s*Genes:\s*(.+)", lines)
        if genes_m:
            genes = [g.strip() for g in genes_m.group(1).split(",")]
        pathways_m = re.search(r"-\s*Pathways:\s*(.+)", lines)
        if pathways_m:
            pathways = [p.strip() for p in pathways_m.group(1).split(",")]
        cell_m = re.search(r"-\s*Cell Types:\s*(.+)", lines)
        if cell_m:
            cell_types = [c.strip() for c in cell_m.group(1).split(",")]
        drugs_m = re.search(r"-\s*Drugs:\s*(.+)", lines)
        if drugs_m:
            drugs = [d.strip() for d in drugs_m.group(1).split(",")]

        hypothesis = {
            "rank": i,
            "title": title,
            "category": category_m.group(1).strip() if category_m else "",
            "_tier": tier,
            "_tier_label": tier_label,
            "_tier_rank": (
                int(source_heading.group("tier_rank")) if source_heading else i
            ),
            "core_claim": claim_m.group(1).strip() if claim_m else "",
            "biological_grounding": (
                biological_grounding_m.group(1).strip()
                if biological_grounding_m
                else ""
            ),
            "target_disease_support": (
                target_disease_support_m.group(1).strip()
                if target_disease_support_m
                else ""
            ),
            "actionability": actionability_m.group(1).strip() if actionability_m else "",
            "interpretation_constraint": (
                interpretation_constraint_m.group(1).strip()
                if interpretation_constraint_m
                else ""
            ),
            "falsifiable_prediction": prediction_m.group(1).strip() if prediction_m else "",
            "validation_approach": validation_m.group(1).strip() if validation_m else "",
            "genes": genes,
            "pathways": pathways,
            "cell_types": cell_types,
            "drugs": drugs,
        }
        if tier_label_m:
            hypothesis["_tier_label"] = tier_label_m.group(1).strip()
        hypotheses.append(hypothesis)

    return hypotheses


def _parse_secondary_stage1_framing_pairs(body: str) -> list[dict[str, str]]:
    """Parse the secondary Stage 1 framing table from markdown Section 4."""
    match = re.search(
        r"^#### Secondary Stage 1 Framing Evidence\s*\n(?P<table>.*?)(?:\n\n|\Z)",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        return []
    pairs: list[dict[str, str]] = []
    for line in match.group("table").splitlines():
        if not line.startswith("|") or "---" in line or "Pair" in line:
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        pairs.append({
            "pair": cells[0],
            "census_direction": cells[1],
            "usage": cells[2],
            "source": cells[3],
        })
    return pairs


def _parse_pipeline_summary(body: str) -> dict[str, Any]:
    """Parse section 5: pipeline execution summary."""
    summary: dict[str, Any] = {}

    m = re.search(r"Total genes assessed:\s*(\d+)", body)
    if m:
        summary["total_genes"] = int(m.group(1))

    m = re.search(r"Featured candidates.*?:\s*(\d+)", body)
    if m:
        summary["featured_count"] = int(m.group(1))

    m = re.search(r"Featured genes:\s*(.+)", body)
    if m:
        summary["featured_genes"] = [g.strip() for g in m.group(1).split(",")]

    return summary


# ---------------------------------------------------------------------------
# Enrichment from target_assessment.json
# ---------------------------------------------------------------------------

def _enrich_from_target_assessment(context: dict, ta_path: Path) -> None:
    """Optionally enrich context with data from target_assessment.json."""
    try:
        ta = json.loads(ta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    # Build gene → matrix entry lookup
    dm = ta.get("druggability_matrix", [])
    gene_lookup: dict[str, dict] = {}
    for entry in dm:
        for key in ("ligand", "receptor"):
            gene = entry.get(key, "")
            if gene and gene not in gene_lookup:
                gene_lookup[gene] = entry

    # Enrich matrix rows
    for row in context.get("matrix", {}).get("rows", []):
        entry = gene_lookup.get(row["gene"])
        if entry:
            row.setdefault("open_targets_score", entry.get("open_targets_score"))
            row.setdefault("is_novel", entry.get("is_novel", False))
            row.setdefault("rank", entry.get("rank"))

    # Add project meta
    meta = ta.get("project_meta", {})
    if meta:
        context.setdefault("project_meta", meta)


# ---------------------------------------------------------------------------
# Markdown-to-HTML helpers
# ---------------------------------------------------------------------------

def _md_to_html(text: str) -> str:
    """Convert simple markdown fragments to HTML."""
    if not text:
        return ""
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Paragraphs (double newlines)
    paragraphs = re.split(r"\n\s*\n", text.strip())
    return "".join(f"<p>{p.strip()}</p>" for p in paragraphs if p.strip())


def _safe_int(val: str) -> int:
    """Parse an integer from a string, returning 0 on failure."""
    try:
        return int(val.strip())
    except (ValueError, AttributeError):
        return 0


def _safe_float(val: str) -> float:
    """Parse a float from a string, returning 0.0 on failure."""
    try:
        return float(val.strip())
    except (ValueError, AttributeError):
        return 0.0


def _safe_optional_float(val: str) -> float | None:
    """Parse a float from a string, returning None on empty or invalid values."""
    try:
        text = val.strip()
        return float(text) if text else None
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# CSS / JS loading
# ---------------------------------------------------------------------------

def _load_css() -> str:
    """Load theme CSS from html-report-generator assets."""
    css_path = _ASSETS_DIR / "theme.css"
    if css_path.exists():
        return css_path.read_text(encoding="utf-8")
    return "/* theme.css not found */"


def _load_js() -> str:
    """Load interactive JS from html-report-generator assets."""
    js_path = _ASSETS_DIR / "interactive.js"
    if js_path.exists():
        return js_path.read_text(encoding="utf-8")
    return "/* interactive.js not found */"


# ---------------------------------------------------------------------------
# Jinja2 custom filters
# ---------------------------------------------------------------------------

def _score_class_filter(value: Any, column: str = "") -> str:
    """Return CSS class for score value color coding."""
    try:
        v = int(value)
    except (ValueError, TypeError):
        return ""
    if column == "safety_profile":
        if v <= -3:
            return "score-critical"
        if v < 0:
            return "score-warning"
        return ""
    if column in ("combined_total", "validated_total", "exploratory_total"):
        if v >= 15:
            return "score-high"
        if v >= 10:
            return "score-medium"
        if v >= 5:
            return "score-low"
        if v < 0:
            return "score-critical"
        return "score-minimal"
    return ""


def _phase_class_filter(phase_str: Any) -> str:
    """Return CSS class for drug phase badge."""
    s = str(phase_str).strip()
    for num in ("4", "3", "2", "1"):
        if num in s:
            return f"drug-phase-{num}"
    return "drug-phase-preclinical"


def _classification_badge_filter(classification: str) -> str:
    """Return CSS class for classification badge."""
    return {
        "validated_target": "badge-validated",
        "exploratory_target": "badge-exploratory",
        "novel_candidate": "badge-novel",
        "insufficient_evidence": "badge-insufficient",
    }.get(classification, "")


def _priority_badge_filter(priority: str) -> str:
    """Return CSS class for priority badge."""
    return {
        "high": "badge-high",
        "medium": "badge-medium",
        "low": "badge-low",
        "unranked": "badge-unranked",
    }.get(priority, "")


# ---------------------------------------------------------------------------
# Jinja2 rendering
# ---------------------------------------------------------------------------

def render_drug_html(context: dict[str, Any]) -> str:
    """Render drug target HTML report from context dictionary."""
    template_path = _TEMPLATE_DIR / "drug_report.html.j2"
    template_str = template_path.read_text(encoding="utf-8")

    env = Environment(loader=BaseLoader(), autoescape=False)
    env.filters["score_class"] = _score_class_filter
    env.filters["phase_class"] = _phase_class_filter
    env.filters["classification_badge"] = _classification_badge_filter
    env.filters["priority_badge"] = _priority_badge_filter
    tmpl = env.from_string(template_str)

    return tmpl.render(**context)


# ---------------------------------------------------------------------------
# Markdown template rendering (drug.md via Jinja2)
# ---------------------------------------------------------------------------


def render_drug_md(
    disease: str,
    stage3_genes: list[str],
    featured_cards: list[dict],
    all_genes_matrix: list[dict],
    stage1_data: dict[str, dict],
    stage1_filter_results: list[dict],
    hypothesis_data: dict | None = None,
    disease_scope: dict | None = None,
    data_limitations: list[str] | None = None,
    interpretations: dict[str, Any] | None = None,
    novelty_opportunity_legend: str = NOVELTY_OPPORTUNITY_LEGEND,
    celltype_resolution: dict | None = None,
) -> str:
    """Render drug.md from structured data via Jinja2 template.

    Mirrors ``render_drug_html`` but produces markdown with ``<!-- EXPAND -->``
    markers for LLM narrative expansion.  Data-heavy formatting (p-value
    scientific notation, inf→N/A, indications join) is done in Python helpers
    so the template stays layout-only.
    """
    template_path = _TEMPLATE_DIR / "drug_report.md.j2"
    template_str = template_path.read_text(encoding="utf-8")

    env = Environment(
        loader=BaseLoader(),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tmpl = env.from_string(template_str)

    # drug.md FEATURED rows = stage3_candidates (rubric ∩ Stage 1 PASS, single narrowed set).
    def _is_validated(r):
        return r.get("stage3_candidate", False)

    featured_rows = sorted(
        [r for r in all_genes_matrix if _is_validated(r)],
        key=lambda r: (r.get("combined_rank_score", r.get("combined_total", 0)), r.get("combined_total", 0)),
        reverse=True,
    )
    other_rows = sorted(
        [r for r in all_genes_matrix if not _is_validated(r)],
        key=lambda r: (r.get("combined_rank_score", r.get("combined_total", 0)), r.get("combined_total", 0)),
        reverse=True,
    )

    # Pre-format complex nested data for template consumption
    preformatted_cards = _preformat_cards(featured_cards, stage1_filter_results)
    formatted_filter = _format_filter_results(stage1_filter_results)
    normalized_hypothesis_data = _normalize_hypothesis_data_for_md(
        hypothesis_data or {}
    )
    celltype_context = _legacy_celltype_context(
        celltype_resolution,
        stage1_data,
    )

    return tmpl.render(
        disease=disease,
        n_genes=len(all_genes_matrix),
        n_featured=len(stage3_genes),
        stage3_genes=stage3_genes,
        featured_cards=preformatted_cards,
        featured_rows=featured_rows,
        other_rows=other_rows,
        stage1_filter_results=formatted_filter,
        hypothesis_data=normalized_hypothesis_data,
        disease_scope=disease_scope or {},
        data_limitations=data_limitations or [],
        interpretations=interpretations or {},
        celltype_context=celltype_context,
        novelty_opportunity_legend=novelty_opportunity_legend,
    )


def _legacy_celltype_context(
    celltype_resolution: dict | None,
    stage1_data: dict[str, dict] | None,
) -> dict[str, Any]:
    resolution = celltype_resolution if isinstance(celltype_resolution, dict) else {}
    input_label = _legacy_celltype_text(
        resolution.get("primary_input_celltype")
    ) or _legacy_celltype_text(resolution.get("interest_celltypes"))
    resolved_label = _legacy_celltype_text(
        resolution.get("primary_resolved_celltype")
    )
    has_explicit_celltype_resolution = bool(input_label or resolved_label)
    match_mode = _legacy_celltype_text(resolution.get("primary_match_mode"))
    if not resolved_label and isinstance(stage1_data, dict):
        for pair in stage1_data.values():
            if not isinstance(pair, dict):
                continue
            census = pair.get("census_validation")
            census = census if isinstance(census, dict) else pair.get("census")
            census = census if isinstance(census, dict) else {}
            resolved_label = _legacy_celltype_text(
                census.get("resolved_cell_type")
            ) or _legacy_celltype_text(census.get("requested_cell_type"))
            if resolved_label:
                break
    proxy = (
        bool(input_label)
        and bool(resolved_label)
        and match_mode == "semantic_proxy"
        and input_label.casefold() != resolved_label.casefold()
    )
    if proxy:
        focus_detail = f"{input_label}; Census proxy: {resolved_label}"
        focus_short = f"interest-cell / {resolved_label.replace(' ', '-')} proxy"
        primary_heading = "Primary Interest-Cell Follow-up Candidates"
    elif (
        not has_explicit_celltype_resolution
        and resolved_label
        and _legacy_is_epithelial_anchor_text(resolved_label)
    ):
        focus_detail = "epithelial/AT2 cell context"
        focus_short = "AT2/epithelial"
        primary_heading = "Primary AT2/Epithelial Follow-up Candidates"
    elif resolved_label:
        focus_detail = resolved_label
        focus_short = "interest-cell"
        primary_heading = "Primary Interest-Cell Follow-up Candidates"
    elif input_label:
        focus_detail = input_label
        focus_short = "interest-cell"
        primary_heading = "Primary Interest-Cell Follow-up Candidates"
    else:
        focus_detail = "resolved interest cell type"
        focus_short = "interest-cell"
        primary_heading = "Primary Interest-Cell Follow-up Candidates"
    return {
        "focus_detail": focus_detail,
        "focus_short": focus_short,
        "primary_heading": primary_heading,
    }


def _legacy_is_epithelial_anchor_text(value: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    normalized = " ".join(normalized.split())
    if not normalized:
        return False
    tokens = set(normalized.split())
    return (
        "at2" in tokens
        or "pulmonary alveolar type 2" in normalized
        or "alveolar type 2" in normalized
        or "alveolar epithelial" in normalized
        or "pulmonary epithelial" in normalized
    )


def _legacy_celltype_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _legacy_celltype_text(item)
            if text:
                return text
    return ""


def _normalize_hypothesis_data_for_md(hypothesis_data: dict) -> dict:
    """Add gene-level buckets for raw hypothesis data before markdown rendering."""
    if not isinstance(hypothesis_data, dict):
        return {}
    normalized = dict(hypothesis_data)
    bucket_keys = (
        "primary_hypotheses",
        "secondary_hypotheses",
        "gene_level_hypotheses",
    )
    if any(key in normalized for key in bucket_keys):
        return normalized
    hypotheses = normalized.get("hypotheses")
    if not isinstance(hypotheses, list):
        return normalized

    rendered_hypotheses: list[Any] = []
    gene_level_hypotheses: list[dict[str, Any]] = []
    unbucketed_hypotheses: list[dict[str, Any]] = []
    for hypothesis in hypotheses:
        if not isinstance(hypothesis, dict):
            rendered_hypotheses.append(hypothesis)
            continue
        references = _hypothesis_reference_list(hypothesis)
        biological_grounding_refs = [
            ref for ref in references if _is_stage1_or_spatial_ref(ref)
        ]
        if biological_grounding_refs:
            rendered_hypotheses.append(hypothesis)
            unbucketed_hypotheses.append(hypothesis)
            continue

        rendered_hypothesis = dict(hypothesis)
        rendered_hypothesis["_tier"] = "gene_level_actionability"
        rendered_hypothesis["_tier_label"] = "Gene-level/actionability follow-up"
        rendered_hypothesis["_tier_note"] = (
            "Cited evidence provides target-disease or actionability context, "
            "but no Stage 1/spatial grounding was cited."
        )
        rendered_hypothesis["_interpretation_constraint"] = (
            "Gene-level support only; do not interpret as AT2-intrinsic or "
            "spatial-niche evidence."
        )
        rendered_hypothesis["_biological_grounding_refs"] = []
        rendered_hypothesis["_target_disease_support_refs"] = [
            ref for ref in references if _is_target_disease_ref(ref)
        ]
        rendered_hypothesis["_actionability_refs"] = [
            ref for ref in references if _is_actionability_ref(ref)
        ]
        gene_level_hypotheses.append(rendered_hypothesis)
        rendered_hypotheses.append(rendered_hypothesis)

    if not gene_level_hypotheses:
        return normalized

    for index, hypothesis in enumerate(gene_level_hypotheses, start=1):
        hypothesis["_tier_rank"] = index
    normalized["hypotheses"] = rendered_hypotheses
    normalized["primary_hypotheses"] = []
    normalized["secondary_hypotheses"] = []
    normalized["gene_level_hypotheses"] = gene_level_hypotheses
    normalized["unbucketed_hypotheses"] = unbucketed_hypotheses
    return normalized


def _hypothesis_reference_list(hypothesis: dict[str, Any]) -> list[str]:
    refs = hypothesis.get("evidence_references")
    if not isinstance(refs, list):
        return []
    return [ref.strip() for ref in refs if isinstance(ref, str) and ref.strip()]


def _is_stage1_or_spatial_ref(ref: str) -> bool:
    normalized = ref.strip().lower()
    return (
        normalized.startswith("stage1_") and normalized.endswith(".json")
    ) or "spatial" in normalized


def _is_target_disease_ref(ref: str) -> bool:
    normalized = ref.strip()
    return normalized.endswith(".json") and (
        normalized.startswith("ot_")
        or normalized.startswith("gwas_")
        or normalized.startswith("genetics_")
    )


def _is_actionability_ref(ref: str) -> bool:
    normalized = ref.strip()
    return normalized.startswith("stage3_") or normalized in {
        "known_drugs.json",
        "resolved_drugs.json",
    }


def _preformat_cards(
    featured_cards: list[dict],
    stage1_filter_results: list[dict] | None = None,
) -> list[dict]:
    """Pre-format featured cards for template rendering.

    Resolves drug indications (isinstance checks), pathway joins, and census
    data so the Jinja2 template only handles simple iteration.

    When ``stage1_filter_results`` is supplied, each formatted pair gets a
    ``_passed`` boolean keyed on the (ligand, receptor) tuple (uppercased for
    case-insensitive matching). Pairs absent from ``stage1_filter_results``
    (and all pairs when the argument is ``None`` or empty) omit the key so the
    template can render the legacy unlabeled output.
    """
    filter_lookup = {
        (row["ligand"].upper(), row["receptor"].upper()): row
        for row in (stage1_filter_results or [])
    }
    result = []
    for card in featured_cards:
        s3 = card.get("stage3", {})
        pairs = card.get("stage1_pairs", {})

        # Pre-format drugs with indications resolved, split by source
        def _fmt_drug(d):
            raw_ind = d.get("indications", [])
            indications = ", ".join(
                (i.get("name", i.get("efo_term", str(i))) if isinstance(i, dict) else str(i))
                for i in raw_ind
            ) or "N/A"
            return {
                "name": d.get("drug_name", "Unknown"),
                "chembl_id": d.get("chembl_id", ""),
                "moa": d.get("mechanism_of_action") or "mechanism not available",
                "phase": d.get("max_phase") or "Preclinical",
                "indications": indications,
                "first_approval": d.get("first_approval"),
            }

        clinical_fmt = [_fmt_drug(d) for d in s3.get("clinical_drugs", [])]
        preclinical_fmt = [_fmt_drug(d) for d in s3.get("preclinical_compounds", [])]
        drugs_fmt = clinical_fmt + preclinical_fmt

        # Pre-format pairs with pathway joins
        pairs_fmt = []
        for _pair_key, pair_data in pairs.items():
            ppi = pair_data.get("string_ppi", {})

            kegg_parts = []
            kegg = pair_data.get("kegg_pathways", {})
            for role, key in [("ligand", "ligand_pathways"), ("receptor", "receptor_pathways")]:
                pws = kegg.get(key, [])
                if pws:
                    kegg_parts.append({"role": role, "pathways": "; ".join(str(p) for p in pws[:3])})

            reactome_parts = []
            reactome = pair_data.get("reactome_pathways", {})
            for role, key in [("ligand", "ligand_pathways"), ("receptor", "receptor_pathways")]:
                pws = reactome.get(key, [])
                if pws:
                    reactome_parts.append({"role": role, "pathways": "; ".join(str(p) for p in pws[:3])})

            census = pair_data.get("census", {})
            ligand = pair_data.get("ligand", "")
            receptor = pair_data.get("receptor", "")
            pair_entry: dict[str, Any] = {
                "ligand": ligand,
                "receptor": receptor,
                # Inline source-file citation so template-baked quantitative
                # lines pass the UNCITED_QUANTITATIVE check in validate_drug_md
                # (regex requires `.json|[from ...]|stage[123]_...` on the same
                # line as any p_value=/risk_ratio= emission).
                "pair_file": f"stage1_{ligand}--{receptor}.json",
                "score": ppi.get("max_combined_score", "N/A"),
                "interaction": "confirmed" if ppi.get("interaction_found", False) else "not found",
                "kegg": kegg_parts,
                "reactome": reactome_parts,
                "census_rr": census.get("risk_ratio"),
                "census_p": census.get("p_value", "N/A"),
            }
            flt = filter_lookup.get((ligand.upper(), receptor.upper()))
            if flt is not None:
                # Mirror _format_filter_results normalization: production rows
                # come from CSV DictReader so `passed` is the string "true" or
                # "false" -- a naive bool(...) would label both truthy.
                raw_passed = flt.get("passed")
                if isinstance(raw_passed, str):
                    pair_entry["_passed"] = raw_passed.lower() == "true"
                else:
                    pair_entry["_passed"] = bool(raw_passed)
            pairs_fmt.append(pair_entry)

        result.append({
            **card,
            "_drugs": drugs_fmt,
            "_clinical_drugs": clinical_fmt,
            "_preclinical_compounds": preclinical_fmt,
            "_pairs": pairs_fmt,
        })

    return result


def _format_filter_results(results: list[dict]) -> list[dict]:
    """Pre-format stage1_filter_results for template rendering.

    Handles: inf→N/A, p-value scientific notation, sorting passed first.
    CSV DictReader returns strings, so all checks are string-based.
    """

    def _fmt_pval(val: str) -> str:
        try:
            v = float(val)
            return f"{v:.2e}" if v < 0.001 else f"{v:.4f}"
        except (ValueError, TypeError):
            return "N/A"

    def _fmt_rr(val: str) -> str:
        if not val or val in ("inf", "Infinity", "-inf", "nan"):
            return "N/A"
        try:
            return f"{float(val):.2f}"
        except (ValueError, TypeError):
            return "N/A"

    formatted = []
    for row in results:
        try:
            string_val = f"{float(row.get('string_combined', 0)):.4f}"
        except (ValueError, TypeError):
            string_val = "N/A"
        try:
            tgt_val = f"{float(row.get('coexpr_target_pct', 0)):.2f}"
        except (ValueError, TypeError):
            tgt_val = "N/A"

        formatted.append({
            **row,
            "_passed": row.get("passed", "").lower() == "true",
            "_string": string_val,
            "_coexpr_p": _fmt_pval(row.get("census_coexpr_pvalue", "1.0")),
            "_gene_a_p": _fmt_pval(row.get("census_gene_a_pvalue", "1.0")),
            "_gene_b_p": _fmt_pval(row.get("census_gene_b_pvalue", "1.0")),
            "_gene_a_rr": _fmt_rr(row.get("gene_a_risk_ratio", "0")),
            "_gene_b_rr": _fmt_rr(row.get("gene_b_risk_ratio", "0")),
            "_coexpr_rr": _fmt_rr(row.get("coexpr_risk_ratio", "0")),
            "_coexpr_tgt": tgt_val,
        })

    # Sort: passed first, then failed; alphabetical by ligand within each group
    formatted.sort(key=lambda r: (not r["_passed"], r.get("ligand", "")))
    return formatted


def build_drug_html_context(data_dir: str) -> dict[str, Any]:
    """Build complete Jinja2 context for drug target HTML report."""
    base = _resolve_data_dir(data_dir)
    drug_md_path = base / "drug.md"

    md_text = drug_md_path.read_text(encoding="utf-8")
    context = parse_drug_md(md_text)

    # Optional enrichment
    ta_path = base / "target_assessment.json"
    if ta_path.exists():
        _enrich_from_target_assessment(context, ta_path)

    # Fallback: load hypothesis from evidence/hypothesis_report.json if parser missed it
    if not context.get("hypothesis"):
        hyp_path = base / "evidence" / "hypothesis_report.json"
        if hyp_path.exists():
            try:
                hyp_data = json.loads(hyp_path.read_text(encoding="utf-8"))
                context["hypothesis"] = [
                    {
                        "rank": h.get("rank", i + 1),
                        "title": h.get("title", ""),
                        "category": h.get("category", ""),
                        "core_claim": h.get("core_claim", ""),
                        "biological_grounding": "",
                        "target_disease_support": "",
                        "actionability": "",
                        "interpretation_constraint": "",
                        "falsifiable_prediction": h.get("falsifiable_prediction", ""),
                        "validation_approach": h.get("validation_approach", ""),
                        "genes": h.get("biological_entities", {}).get("genes", []),
                        "pathways": h.get("biological_entities", {}).get("pathways", []),
                        "cell_types": h.get("biological_entities", {}).get("cell_types", []),
                        "drugs": h.get("biological_entities", {}).get("drugs", []),
                    }
                    for i, h in enumerate(hyp_data.get("hypotheses", []))
                ]
                context["primary_hypotheses"] = hyp_data.get("primary_hypotheses", [])
                context["secondary_hypotheses"] = hyp_data.get("secondary_hypotheses", [])
                context["gene_level_hypotheses"] = hyp_data.get(
                    "gene_level_hypotheses",
                    [],
                )
                context["unbucketed_hypotheses"] = hyp_data.get(
                    "unbucketed_hypotheses",
                    [],
                )
                context["secondary_stage1_framing_pairs"] = hyp_data.get(
                    "secondary_stage1_framing_pairs",
                    [],
                )
            except Exception:
                pass

    # Embed CSS/JS
    context["css"] = _load_css()
    context["js"] = _load_js()
    context["generation_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    return context


# ---------------------------------------------------------------------------
# LangChain tool
# ---------------------------------------------------------------------------

@tool
def generate_drug_html_report(data_dir: str) -> str:
    """Generate a self-contained HTML report from drug.md.

    Reads drug.md and optionally target_assessment.json from data_dir,
    renders via Jinja2 template with embedded CSS/JS, and saves
    drug_report.html to the same directory.

    Args:
        data_dir: Directory containing drug.md

    Returns:
        JSON with generation status, output path, and statistics
    """
    base = _resolve_data_dir(data_dir)
    drug_md_path = base / "drug.md"

    if not drug_md_path.exists():
        return json.dumps({"error": "drug.md not found", "path": str(drug_md_path)})

    try:
        context = build_drug_html_context(data_dir)
        html = render_drug_html(context)
    except Exception as exc:
        return json.dumps({
            "generated": False,
            "error": f"HTML rendering failed: {exc}",
            "path": str(base / "drug_report.html"),
        }, indent=2)

    output_path = base / "drug_report.html"
    output_path.write_text(html, encoding="utf-8")

    return json.dumps({
        "generated": True,
        "path": str(output_path),
        "size_bytes": len(html.encode("utf-8")),
        "gene_count": len(context.get("matrix", {}).get("rows", [])),
        "deep_dive_count": len(context.get("deep_dives", [])),
        "featured_candidates": len(context.get("executive_summary", {}).get("featured_candidates", [])),
    }, indent=2)

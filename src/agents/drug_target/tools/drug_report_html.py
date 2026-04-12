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
        elif header_line.startswith("4.") and "Hypothesis" in header_line:
            context["hypothesis"] = _parse_hypothesis_section(body)
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
    """Parse the 14-column pipe-delimited druggability table and scoring legend."""
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
                "classification": cells[11].strip() if len(cells) > 11 else "",
                "priority": cells[12].strip() if len(cells) > 12 else "",
                "stage3": cells[13].strip().lower() == "yes" if len(cells) > 13 else False,
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
        "Combined", "Classification", "Priority", "Stage3",
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
            "literature": [],
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


def _parse_literature(body: str) -> list[dict[str, str]]:
    """Parse PMID links into structured reference list."""
    refs: list[dict[str, str]] = []
    for m in re.finditer(
        r"\[PMID:\s*(\d+)\]\((https?://[^)]+)\)\s*—\s*\"([^\"]+)\"",
        body,
    ):
        refs.append({
            "pmid": m.group(1),
            "url": m.group(2),
            "title": m.group(3),
        })
    return refs


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
    """Parse section 4 (Hypothesis-Driven Analysis) into structured list."""
    hypotheses: list[dict[str, Any]] = []

    # Split on ### 4.N. headings
    h_sections = re.split(r"^### \d+\.\d+\.\s+", body, flags=re.MULTILINE)

    for i, sec in enumerate(h_sections):
        if not sec.strip() or i == 0:
            continue  # skip preamble before first ###

        lines = sec.strip()
        title = lines.split("\n", 1)[0].strip()

        category_m = re.search(r"\*\*Category:\*\*\s*(.+)", lines)
        claim_m = re.search(r"\*\*Core Claim:\*\*\s*(.+)", lines)
        prediction_m = re.search(r"\*\*Falsifiable Prediction:\*\*\s*(.+)", lines)
        validation_m = re.search(r"\*\*Validation Approach:\*\*\s*(.+)", lines)

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

        hypotheses.append({
            "rank": i,
            "title": title,
            "category": category_m.group(1).strip() if category_m else "",
            "core_claim": claim_m.group(1).strip() if claim_m else "",
            "falsifiable_prediction": prediction_m.group(1).strip() if prediction_m else "",
            "validation_approach": validation_m.group(1).strip() if validation_m else "",
            "genes": genes,
            "pathways": pathways,
            "cell_types": cell_types,
            "drugs": drugs,
        })

    return hypotheses


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
    data_limitations: list[str] | None = None,
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

    # Pre-sort matrix rows: stage3 first (desc combined), then rest (desc combined)
    featured_rows = sorted(
        [r for r in all_genes_matrix if r.get("stage3_candidate")],
        key=lambda r: r.get("combined_total", 0),
        reverse=True,
    )
    other_rows = sorted(
        [r for r in all_genes_matrix if not r.get("stage3_candidate")],
        key=lambda r: r.get("combined_total", 0),
        reverse=True,
    )

    # Pre-format complex nested data for template consumption
    preformatted_cards = _preformat_cards(featured_cards)
    formatted_filter = _format_filter_results(stage1_filter_results)

    return tmpl.render(
        disease=disease,
        n_genes=len(all_genes_matrix),
        n_featured=len(stage3_genes),
        stage3_genes=stage3_genes,
        featured_cards=preformatted_cards,
        featured_rows=featured_rows,
        other_rows=other_rows,
        stage1_filter_results=formatted_filter,
        hypothesis_data=hypothesis_data or {},
        data_limitations=data_limitations or [],
    )


def _preformat_cards(featured_cards: list[dict]) -> list[dict]:
    """Pre-format featured cards for template rendering.

    Resolves drug indications (isinstance checks), pathway joins, and census
    data so the Jinja2 template only handles simple iteration.
    """
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
            pairs_fmt.append({
                "ligand": pair_data.get("ligand", ""),
                "receptor": pair_data.get("receptor", ""),
                "score": ppi.get("max_combined_score", "N/A"),
                "interaction": "confirmed" if ppi.get("interaction_found", False) else "not found",
                "kegg": kegg_parts,
                "reactome": reactome_parts,
                "census_rr": census.get("risk_ratio"),
                "census_p": census.get("p_value", "N/A"),
            })

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
                        "falsifiable_prediction": h.get("falsifiable_prediction", ""),
                        "validation_approach": h.get("validation_approach", ""),
                        "genes": h.get("biological_entities", {}).get("genes", []),
                        "pathways": h.get("biological_entities", {}).get("pathways", []),
                        "cell_types": h.get("biological_entities", {}).get("cell_types", []),
                        "drugs": h.get("biological_entities", {}).get("drugs", []),
                    }
                    for i, h in enumerate(hyp_data.get("hypotheses", []))
                ]
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

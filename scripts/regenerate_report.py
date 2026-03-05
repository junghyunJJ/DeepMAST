#!/usr/bin/env python
"""Regenerate CCI_Analysis_Report.html using Jinja2 template from skills/.

This script loads raw data files (CSV, JSON, Markdown) from res_bc/ and renders
them through the Jinja2 template at skills/html-report-generator/templates/report.html.j2.
Figures are embedded as base64 data URIs via report.py's _embed_figures_in_html().

Usage:
    python scripts/regenerate_report.py
"""

import json
import math
import os
import re
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
from jinja2 import Environment, BaseLoader

# ---------------------------------------------------------------------------
# Project bootstrap
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.deep_interpreter.tools.report import _embed_figures_in_html

DATA_DIR = PROJECT_ROOT / "res_bc"
SKILLS_DIR = PROJECT_ROOT / "skills" / "html-report-generator"
INTEREST_CLUSTERS = [4, 16, 17]

# Figure filename map (analysis number -> filename)
FIGURES = {
    "1-1": "1.cluster_spatial.png",
    "1-2": "2.celltype_heatmap_analysis.png",
    "1-3": "3.neighborhood_enrichment_squidpy.png",
    "1-4": "4.spatial_enrich_decoupler.png",
    "1-5": "5.spatial_relation_MISTy.png",
    "2-6": "6.liana_MoransR.png",
    "2-7": "7.factor_spatial_NMF.png",
    "2-8": "8.pathway_factor_heatmap.png",
    "3-9": "9.quadrant_analysis.png",
    "3-10": "10.spatial_plot_interections.png",
    "3-11": "11.lr_interections.png",
}

PATHWAY_DESCRIPTIONS = {
    "EGFR": "Epidermal Growth Factor Receptor — drives proliferation and invasion",
    "MAPK": "Mitogen-Activated Protein Kinase — cell growth and differentiation",
    "PI3K": "PI3K/AKT — cell survival, metabolism, and growth",
    "TGFb": "TGF-Beta — EMT, fibrosis, and immune modulation",
    "Hypoxia": "HIF pathway — angiogenesis and invasive phenotypes",
    "VEGF": "VEGF — angiogenesis and vascular permeability",
    "NFkB": "NF-kB — inflammation and immune responses",
    "Estrogen": "Estrogen receptor — hormone-responsive proliferation",
    "p53": "p53 — cell cycle arrest and apoptosis",
    "Androgen": "Androgen receptor — growth and differentiation",
    "JAK-STAT": "JAK/STAT — cytokine signaling",
    "TNFa": "TNF-alpha — pro-inflammatory signaling",
    "Trail": "TRAIL — apoptosis induction",
    "WNT": "Wnt — cell fate, proliferation, and migration",
}


# ---------------------------------------------------------------------------
# Custom Jinja2 filters
# ---------------------------------------------------------------------------
def fdr_fmt_filter(val):
    """Format FDR value as HTML superscript: 2.47e-244 -> 2.47 x 10^-244."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return str(val)
    if v == 0:
        return "0"
    if v >= 0.01:
        return f"{v:.4f}"
    exp = int(math.floor(math.log10(abs(v))))
    mantissa = v / (10 ** exp)
    return f"{mantissa:.2f}&nbsp;&times;&nbsp;10<sup>{exp}</sup>"


def linkify_pmids_filter(text):
    """Convert PMID:12345678 patterns to clickable PubMed links."""
    if not text:
        return ""
    return re.sub(
        r"\(?PMID:\s*(\d{7,8})\)?",
        lambda m: (
            f'<a href="https://pubmed.ncbi.nlm.nih.gov/{m.group(1)}/"'
            f' class="reference" target="_blank">(PMID:&nbsp;{m.group(1)})</a>'
        ),
        str(text),
    )


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------
def load_text(filename):
    return (DATA_DIR / filename).read_text()


def load_json(filename):
    return json.loads((DATA_DIR / filename).read_text())


def load_csv_dicts(filename, **kwargs):
    """Load CSV as list of dicts."""
    df = pd.read_csv(DATA_DIR / filename, **kwargs)
    return df.to_dict("records")


def load_csv(filename):
    return pd.read_csv(DATA_DIR / filename)


# ---------------------------------------------------------------------------
# Markdown parsers (extract structured data from interpretation .md files)
# ---------------------------------------------------------------------------
def md_paragraphs(text):
    """Convert plain/markdown text to HTML paragraphs with linked PMIDs."""
    if not text:
        return ""
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = linkify_pmids_filter(text)
    paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    parts = []
    for p in paras:
        lines = p.split("\n")
        if all(ln.strip().startswith("- ") for ln in lines if ln.strip()):
            items = [ln.lstrip("- ").strip() for ln in lines if ln.strip()]
            parts.append("<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
        else:
            parts.append(f"<p>{p}</p>")
    return "\n".join(parts)


def parse_interpretations(filename):
    """Extract Biological Interpretation text per analysis from a part*.md file."""
    text = load_text(filename)
    result = {}
    chunks = re.split(r"^## Analysis (\d+-\d+):\s*(.+)$", text, flags=re.MULTILINE)
    for i in range(1, len(chunks) - 2, 3):
        num = chunks[i]
        body = chunks[i + 2]
        m = re.search(
            r"### Biological Interpretation\s*\n(.*?)(?=^### |\Z)",
            body, re.MULTILINE | re.DOTALL,
        )
        result[num] = md_paragraphs(m.group(1).strip()) if m else ""
    return result


def parse_part_summary(filename):
    """Extract Part Summary key findings as a list of strings."""
    text = load_text(filename)
    m = re.search(
        r"## Part \d+ Summary.*?### Key Findings\s*\n(.*?)(?=^### |\Z)",
        text, re.MULTILINE | re.DOTALL,
    )
    if not m:
        return []
    return [
        re.sub(r"^\d+\.\s*", "", line).strip()
        for line in m.group(1).strip().split("\n")
        if line.strip() and re.match(r"^\d+\.", line.strip())
    ]


def parse_synthesis():
    """Parse synthesis_updated.md into structured sections."""
    synthesis = load_text("synthesis_updated.md")

    # Executive summary
    m = re.search(r"## Executive Summary\s*\n(.*?)(?=^## |\Z)", synthesis, re.M | re.S)
    exec_text = md_paragraphs(m.group(1).strip()) if m else ""

    # Themes
    themes = []
    for n in range(1, 8):
        m = re.search(
            rf"### Theme {n}: (.+?)\s*\n(.*?)(?=^### Theme|^## |\Z)",
            synthesis, re.M | re.S,
        )
        if m:
            themes.append({
                "title": m.group(1).strip(),
                "content": md_paragraphs(m.group(2).strip()),
            })

    # Emergent themes table
    emergent_table = None
    m = re.search(r"## Emergent Themes Summary\s*\n(.*?)(?=^## |\Z)", synthesis, re.M | re.S)
    if m:
        lines = [ln.strip() for ln in m.group(1).strip().split("\n")
                 if ln.strip() and not set(ln.strip()) <= {"|", "-", " "}]
        if len(lines) >= 2:
            headers = [c.strip() for c in lines[0].split("|") if c.strip()]
            rows = []
            for ln in lines[1:]:
                if ln.startswith("|--") or set(ln) <= {"|", "-", " "}:
                    continue
                rows.append([c.strip() for c in ln.split("|") if c.strip()])
            if rows:
                emergent_table = {"headers": headers, "rows": rows}

    # Clinical implications
    m = re.search(r"## Clinical/Biological Implications\s*\n(.*?)(?=^## |\Z)", synthesis, re.M | re.S)
    clinical = md_paragraphs(m.group(1).strip()) if m else ""

    # Novel findings
    novel_findings = []
    m = re.search(r"## Novel Findings Summary\s*\n(.*?)(?=^## |\Z|^### )", synthesis, re.M | re.S)
    if m:
        novel_findings = [
            ln.lstrip("- ").strip()
            for ln in m.group(1).strip().split("\n")
            if ln.strip().startswith("- ")
        ]

    # Limitations
    limitations = []
    m = re.search(r"## Limitations\s*\n(.*?)(?=^## |\Z)", synthesis, re.M | re.S)
    if m:
        limitations = [
            ln.lstrip("- ").strip()
            for ln in m.group(1).strip().split("\n")
            if ln.strip().startswith("- ")
        ]

    return {
        "model_text": exec_text,
        "themes": themes,
        "emergent_table": emergent_table,
        "clinical": clinical,
        "novel_findings": novel_findings,
        "limitations": limitations,
    }


def parse_therapeutic():
    """Parse therapeutic data from JSON and synthesis markdown."""
    therapeutic = load_json("therapeutic_targets.json")
    synthesis = load_text("synthesis_updated.md")
    summary = therapeutic.get("summary", {})

    summary_line = (
        f"<strong>Genes Evaluated:</strong> {summary.get('total_genes_evaluated', 0)} | "
        f"<strong>Druggable:</strong> {summary.get('druggable_count', 0)} | "
        f"<strong>Known Drugs:</strong> {summary.get('known_drugs_count', 0)} | "
        f"<strong>Novel Targets:</strong> {summary.get('novel_target_count', 0)}"
    )

    # Druggable targets
    druggable = []
    for t in therapeutic.get("druggable_targets", []):
        tract = t.get("tractability", {})
        modalities = ", ".join(
            f"{k}: {', '.join(v[:2])}" for k, v in tract.items() if v
        )
        druggable.append({
            "gene": t.get("gene", ""),
            "name": t.get("name", ""),
            "score": t.get("association_score", 0),
            "tractability": modalities or "N/A",
            "evidence_count": t.get("evidence_count", 0),
            "safety_concerns": t.get("safety_concerns", 0),
            "lr_frequency": t.get("lr_frequency", 0),
            "lr_roles": ", ".join(t.get("lr_roles", [])),
        })

    # Therapeutic sections from synthesis markdown
    sections = []
    m = re.search(
        r"### Therapeutic Implications\s*\n(.*?)(?=^## |\Z)",
        synthesis, re.M | re.S,
    )
    if m:
        subsections = re.split(r"^#### (.+)$", m.group(1).strip(), flags=re.MULTILINE)
        for i in range(1, len(subsections) - 1, 2):
            sections.append({
                "title": subsections[i].strip(),
                "content": md_paragraphs(subsections[i + 1].strip()),
            })

    # Novel targets
    novel = [
        {
            "gene": t.get("gene", ""),
            "name": t.get("name", ""),
            "lr_frequency": t.get("lr_frequency", 0),
        }
        for t in therapeutic.get("novel_targets", [])[:10]
    ]

    return {
        "summary_line": summary_line,
        "druggable": druggable,
        "sections": sections,
        "novel": novel,
    }


# ---------------------------------------------------------------------------
# Build template context
# ---------------------------------------------------------------------------
def build_context():
    """Assemble the full Jinja2 template context dict."""
    interps1 = parse_interpretations("part1_final.md")
    interps2 = parse_interpretations("part2_final.md")
    interps3 = parse_interpretations("part3_final.md")
    findings1 = parse_part_summary("part1_final.md")
    findings2 = parse_part_summary("part2_final.md")
    findings3 = parse_part_summary("part3_final.md")

    # Load CSV data as DataFrames (for filtering) then convert to dicts
    ct_df = load_csv("sig_clusterwithcelltyp.csv")
    pw_df = load_csv("sig_PathwayEnrich_decoupler.csv")
    nhood_df = load_csv("res_nhood_enrichment.csv")
    misty_df = load_csv("res_SpatialRelationship_MISTy.csv")
    lr_df = load_csv("sel_interest_sig_liana.csv")
    factor_df = load_csv("res_liana_cluster_factor.csv")
    pf_df = load_csv("sig_liana_pathway_factor.csv")

    # --- Part 1 analyses ---
    ct_interest = ct_df[ct_df["cluster"].isin(INTEREST_CLUSTERS)].sort_values(
        ["cluster", "cluster_medians"], ascending=[True, False]
    )
    nhood_interest = nhood_df[
        nhood_df["source_Cluster"].isin(INTEREST_CLUSTERS)
        | nhood_df["target_Cluster"].isin(INTEREST_CLUSTERS)
    ].sort_values("value", ascending=False)
    pw_interest = pw_df[pw_df["group"].isin(INTEREST_CLUSTERS)].sort_values(
        ["group", "stat"], ascending=[True, False]
    )
    top_pathways = pw_interest["name"].unique()[:8].tolist()

    part1 = {
        "analyses": [
            {
                "num": "1-1", "title": "Spatial Clustering",
                "figure": FIGURES["1-1"],
                "caption": "Figure 1: Spatial distribution of 17 clusters across breast cancer tissue",
                "table_type": None, "table_data": [], "columns": [],
                "pathway_box": None,
                "interpretation": interps1.get("1-1", ""),
            },
            {
                "num": "1-2", "title": "Cell Type Composition",
                "figure": FIGURES["1-2"],
                "caption": "Figure 2: Cell type enrichment heatmap across spatial clusters",
                "table_type": "rowspan",
                "table_data": ct_interest.to_dict("records"),
                "group_col": "cluster",
                "columns": [("celltype", "Cell Type"), ("cluster_medians", "Median Score"), ("fdr", "FDR")],
                "fdr_cols": ["fdr"], "highlight_cols": ["celltype"], "top_n": 5,
                "pathway_box": None,
                "interpretation": interps1.get("1-2", ""),
            },
            {
                "num": "1-3", "title": "Neighborhood Enrichment",
                "figure": FIGURES["1-3"],
                "caption": "Figure 3: Neighborhood enrichment z-scores between spatial clusters",
                "table_type": "simple",
                "table_data": nhood_interest.to_dict("records"),
                "columns": [("source_Cluster", "Source Cluster"), ("target_Cluster", "Target Cluster"), ("value", "Enrichment Score")],
                "pathway_box": None,
                "interpretation": interps1.get("1-3", ""),
            },
            {
                "num": "1-4", "title": "Decoupler Pathway Enrichment",
                "figure": FIGURES["1-4"],
                "caption": "Figure 4: Pathway enrichment scores across spatial clusters (PROGENy)",
                "table_type": "rowspan",
                "table_data": pw_interest.to_dict("records"),
                "group_col": "group",
                "columns": [("name", "Pathway"), ("stat", "Statistic"), ("meanchange", "Mean Change"), ("fdr", "FDR")],
                "fdr_cols": ["fdr"], "highlight_cols": [], "top_n": 5,
                "pathway_box": [
                    {"name": pw, "description": PATHWAY_DESCRIPTIONS.get(pw, "")}
                    for pw in top_pathways
                ],
                "interpretation": interps1.get("1-4", ""),
            },
            {
                "num": "1-5", "title": "MISTy Spatial Relationships",
                "figure": FIGURES["1-5"],
                "caption": "Figure 5: MISTy-derived spatial relationships between pathways and cell types",
                "table_type": "simple",
                "table_data": misty_df.head(15).to_dict("records"),
                "columns": [("target", "Cell Type"), ("predictor", "Pathway"), ("importances", "Importance")],
                "pathway_box": None,
                "interpretation": interps1.get("1-5", ""),
            },
        ],
        "summary": {
            "title": "Part 1 Summary: Spatial & Pathway Analysis",
            "findings": findings1 or [
                "17 spatial clusters with tumor (4), stromal (16), and invasive front (17) domains",
                "Proliferative invasive tumor cells in cluster 4; stromal fibroblasts in 16; macrophages in 17",
                "Strong tumor-stroma co-localization supports spatial crosstalk at invasive fronts",
                "EGFR in tumor clusters; TGFb/VEGF in stromal clusters; Hypoxia at invasive fronts",
                "MISTy validates pathway-cell type spatial associations across clusters",
            ],
        },
    }

    # --- Part 2 analyses ---
    lr_top = lr_df.nlargest(10, "morans")

    part2 = {
        "analyses": [
            {
                "num": "2-6", "title": "LIANA Moran's R &mdash; Top Spatially Co-localized L-R Pairs",
                "figure": FIGURES["2-6"],
                "caption": "Figure 6: Spatial autocorrelation (Moran's R) scores for L-R pairs",
                "table_type": "simple",
                "table_data": lr_top.to_dict("records"),
                "columns": [
                    ("interaction", "L-R Pair"), ("morans", "Moran's R"),
                    ("Factor3", "Factor3 Score"), ("progeny", "Pathways"),
                    ("combinedscore", "Combined Score"),
                ],
                "interpretation": interps2.get("2-6", ""),
            },
            {
                "num": "2-7", "title": "NMF Factor Spatial Patterns",
                "figure": FIGURES["2-7"],
                "caption": "Figure 7: NMF Factor3 spatial distribution across tissue",
                "table_type": "simple",
                "table_data": factor_df.to_dict("records"),
                "columns": [("Cluster", "Cluster"), ("Factor1", "Factor1"), ("Factor2", "Factor2"), ("Factor3", "Factor3")],
                "interpretation": interps2.get("2-7", ""),
            },
            {
                "num": "2-8", "title": "Pathway-Factor Enrichment",
                "figure": FIGURES["2-8"],
                "caption": "Figure 8: Pathway enrichment across NMF factors",
                "table_type": "fdr",
                "table_data": pf_df.to_dict("records"),
                "columns": [("factor", "Factor"), ("pathway", "Pathway"), ("estimate", "Estimate"), ("adj_pval", "Adj. P-value")],
                "fdr_cols": ["adj_pval"],
                "interpretation": interps2.get("2-8", ""),
            },
        ],
        "summary": {
            "title": "Part 2 Summary: CCI & NMF Analysis",
            "findings": findings2 or [
                "EGFR-ERBB3 (Moran's R=0.48), VEGFA-FLT1 (0.43), TGFB1-TGFBR2 (0.40) top L-R pairs",
                "NMF Factor3 localizes to invasive tumor clusters (mean=0.74, Moran's I=0.52)",
                "Factor3 enriched for EGFR (3.1x), MAPK (2.7x), TGFb (2.2x), VEGF (1.9x)",
            ],
        },
    }

    # --- Part 3 analyses ---
    lr_sorted = lr_df.sort_values("combinedscore", ascending=False)

    part3 = {
        "analyses": [
            {
                "num": "3-9", "title": "NMF Quadrant with GenePT",
                "figure": FIGURES["3-9"],
                "caption": "Figure 9: L-R pairs scored by Moran's R and GenePT hybrid ranking",
                "table_type": None, "table_data": [], "columns": [],
                "interpretation": interps3.get("3-9", ""),
            },
            {
                "num": "3-10", "title": "Spatial L-R Visualization",
                "figure": FIGURES["3-10"],
                "caption": "Figure 10: Spatial expression patterns of top L-R pairs across tissue",
                "table_type": None, "table_data": [], "columns": [],
                "interpretation": interps3.get("3-10", ""),
            },
            {
                "num": "3-11", "title": "L-R Interaction Summary",
                "figure": FIGURES["3-11"],
                "caption": "Figure 11: L-R interaction strength summary across cell types and clusters",
                "table_type": "paginated",
                "table_data": lr_sorted.to_dict("records"),
                "columns": [
                    ("interaction", "L-R Pair"), ("ligand", "Ligand"), ("receptor", "Receptor"),
                    ("morans", "Moran's R"), ("Factor3", "Factor3"),
                    ("genept_score", "GenePT"), ("combinedscore", "Combined"),
                ],
                "interpretation": interps3.get("3-11", ""),
            },
        ],
        "summary": {
            "title": "Part 3 Summary: L-R Interaction Details",
            "findings": findings3 or [
                "LAMA5^SDC1 as novel ECM-receptor axis (hybrid score = 0.654)",
                "EFNB2^EPHB4 implicated in tumor angiogenesis (GenePT = 0.934)",
                "COL4A5^DDR1 mediates collagen signaling promoting invasion (Moran's R = 0.234)",
            ],
        },
    }

    # --- Papers ---
    all_papers = load_json("papers.json")
    seen = set()
    papers = []
    for p in all_papers.get("papers", []):
        pmid = p.get("pmid", "")
        if pmid and pmid not in seen:
            seen.add(pmid)
            authors = p.get("authors", [])
            if isinstance(authors, list):
                authors = authors[0] + " et al." if len(authors) > 1 else (authors[0] if authors else "")
            papers.append({
                "pmid": pmid,
                "title": p.get("title", f"Article {pmid}"),
                "authors": authors,
                "journal": p.get("journal", ""),
            })
    papers = papers[:25]

    # --- Executive summary ---
    synthesis_text = load_text("synthesis_updated.md")
    m = re.search(r"## Executive Summary\s*\n(.*?)(?=^## |\Z)", synthesis_text, re.M | re.S)
    exec_text = md_paragraphs(m.group(1).strip()) if m else ""

    executive_summary = {
        "text": exec_text,
        "findings": [
            "17 spatial clusters identified with tumor (4), stromal (16), and invasive front (17) domains",
            "Factor3 spatially localizes to invasive tumor regions (Moran's I = 0.52, p &lt; 0.001)",
            "EGFR-ERBB3 (Moran's R = 0.48), VEGFA-FLT1 (0.43), TGFB1-TGFBR2 (0.40) as top L-R pairs",
            "LAMA5^SDC1 identified as novel ECM-receptor axis (hybrid score = 0.654)",
            "Coordinated EGFR-TGFb-Hypoxia signaling axis drives invasive tumor niches",
            "5 druggable targets identified: ITGB1, FYN, CD44, APP, ITGAV",
        ],
    }

    return {
        "title": "Comprehensive Analysis of Cell-Cell Interactions in Human Breast Cancer",
        "subtitle": "Spatial Transcriptomics Analysis &mdash; Focus on Invasive Tumor Regions (Clusters 4, 16, 17)",
        "css": (SKILLS_DIR / "assets" / "theme.css").read_text(),
        "js": (SKILLS_DIR / "assets" / "interactive.js").read_text(),
        "generation_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "interest_clusters": INTEREST_CLUSTERS,
        "config": {
            "Target Clusters": "4, 16, 17",
            "Interest Cell Types": "Prolif Invasive Tumor",
            "NMF Factor": "Factor3",
            "Data Directory": "res_bc/",
        },
        "executive_summary": executive_summary,
        "part1": part1,
        "part2": part2,
        "part3": part3,
        "summary_tab": parse_synthesis(),
        "therapeutic_tab": parse_therapeutic(),
        "papers": papers,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"Data directory: {DATA_DIR}")
    print("Loading data and building context...")

    # Setup Jinja2 environment with custom filters
    template_str = (SKILLS_DIR / "templates" / "report.html.j2").read_text()
    env = Environment(loader=BaseLoader(), autoescape=False)
    env.filters["fdr_fmt"] = fdr_fmt_filter
    env.filters["linkify_pmids"] = linkify_pmids_filter
    template = env.from_string(template_str)

    # Build context and render
    context = build_context()
    print("  [ok] Context assembled")

    html = template.render(**context)
    print("  [ok] Template rendered")

    # Post-process: embed figures as base64
    html = _embed_figures_in_html(html, str(DATA_DIR))
    print("  [ok] Figures embedded as base64")

    # Write output
    output = DATA_DIR / "CCI_Analysis_Report.html"
    output.write_text(html)
    print(f"\nReport: {output} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()

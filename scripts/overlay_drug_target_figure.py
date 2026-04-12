#!/usr/bin/env python3
"""Generate Drug Target Agent Medea-style figure programmatically.

Full programmatic rendering using matplotlib for Nature Methods quality.
Produces a 4-subagent vertical pipeline with 8 annotated side panels
showing real input/output data from the breast cancer case study.

Usage:
    python scripts/overlay_drug_target_figure.py
    python scripts/overlay_drug_target_figure.py --output fig/custom_name.png
    python scripts/overlay_drug_target_figure.py --dpi 600  # higher resolution
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.patheffects as pe
import numpy as np


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FIG_W, FIG_H = 7.2, 10.8  # inches (183mm x 274mm) — taller for breathing room
DPI = 300

# Column boundaries (fraction of fig width)
LEFT_X0, LEFT_X1 = 0.02, 0.26
CENTER_X0, CENTER_X1 = 0.31, 0.69
RIGHT_X0, RIGHT_X1 = 0.74, 0.98

# Vertical positions for 4 module rows (top to bottom, in axes coords)
ROW_TOPS = [0.80, 0.60, 0.40, 0.20]
MODULE_H = 0.13
PANEL_H = 0.12

# Colors (Okabe-Ito safe, muted for publication)
COLORS = {
    "evidence_assessor": {"fill": "#DCEEFB", "border": "#1565C0", "text": "#0D47A1"},
    "deep_diver":        {"fill": "#DCEEDC", "border": "#2E7D32", "text": "#1B5E20"},
    "hypothesis_writer": {"fill": "#ECDCF5", "border": "#6A1B9A", "text": "#4A148C"},
    "report_writer":     {"fill": "#FFF3D0", "border": "#E65100", "text": "#BF360C"},
    "panel":             {"fill": "#F5F5F5", "border": "#D0D0D0", "text": "#424242"},
    "arrow":             "#757575",
    "dashed":            "#B0B0B0",
    "bg":                "#FFFFFF",
}

# Module definitions
MODULES = [
    {
        "key": "evidence_assessor",
        "title": "Evidence Assessor",
        "subtitle": "Multi-database target validation & rubric scoring",
        "ribbon": "Stage 2 (OpenTargets + GWAS + VEP)  \u2192  Rubric Scoring  \u2192  Stage 1 (STRING + Census)",
        "badge": "17 tools",
    },
    {
        "key": "deep_diver",
        "title": "Deep Diver",
        "subtitle": "Drug profiles & literature evidence per FEATURED gene",
        "ribbon": "ChEMBL query  \u2192  PubMed search  \u2192  Stage 3 Gate",
        "badge": "per gene",
    },
    {
        "key": "hypothesis_writer",
        "title": "Hypothesis Writer",
        "subtitle": "Mechanistic hypotheses with UCB scoring",
        "ribbon": "Evidence ingestion  \u2192  4-category generation  \u2192  Gap analysis  \u2192  UCB filter",
        "badge": "4\u20136 hypotheses",
    },
    {
        "key": "report_writer",
        "title": "Report Writer",
        "subtitle": "Anti-hallucination validated publication report",
        "ribbon": "Reference Card  \u2192  Draft  \u2192  Validation loop (max 5)  \u2192  Quality gate",
        "badge": "\u03b8 \u2265 0.7",
    },
]

# Left panels (input/intermediate)
LEFT_PANELS = [
    {
        "header": "Input: L-R Candidates",
        "body": (
            '{\n'
            '  "pairs": [\n'
            '    {"ligand": "EFNB2",\n'
            '     "receptor": "EPHB4",\n'
            '     "score": 0.578, "rank": 1},\n'
            '    {"ligand": "TNFSF10",\n'
            '     "receptor": "TNFRSF10C",\n'
            '     "score": 0.527, "rank": 2},\n'
            '    ...\n'
            '  ]\n'
            '}'
        ),
    },
    {
        "header": "Disease Context",
        "body": (
            "Disease: Breast cancer\n"
            "Total genes assessed: 10\n"
            "Unique L-R pairs: 30\n"
            "FEATURED: DDR1, MUC1, TGFB1\n"
            "NOVEL: COL4A5, SEMA3F\n"
            "Selection: combined_total \u2265 10"
        ),
    },
    {
        "header": "Evidence Inventory",
        "body": (
            "Stage 2: 10 genes \u00d7 3 databases\n"
            "  OpenTargets, GWAS, Ensembl VEP\n"
            "Stage 1: 3 FEATURED pairs\n"
            "  STRING PPI: 0.873\u20130.999\n"
            "  Census co-expr: p < 0.05\n"
            "Stage 3: ChEMBL + PubMed / gene"
        ),
    },
    {
        "header": "Reference Card (SSOT)",
        "body": (
            "build_evidence_summary()\n"
            "compiles all Stage 1\u20133 evidence.\n"
            "\n"
            "Evidence hierarchy:\n"
            " 1. Reference Card (truth)\n"
            " 2. Evidence files (suppl.)\n"
            " 3. \u201cData not available\u201d\n"
            " 4. General knowledge: NEVER"
        ),
    },
]

# Right panels (output/reasoning)
RIGHT_PANELS = [
    {
        "header": "Rubric Assessment",
        "body": (
            "DDR1: validated_target (13)\n"
            "  Drug evid: +2 | GWAS: +2\n"
            "  Mechanism: +2 | Tract: +2\n"
            "  Biological: +2| Clinical: +2\n"
            "  Safety: +1\n"
            "  Priority: HIGH \u2192 FEATURED\n"
            "\n"
            "MUC1: exploratory (10)\n"
            "  \u2192 FEATURED"
        ),
    },
    {
        "header": "Drug Profile",
        "body": (
            "DDR1 \u2014 ChEMBL profile:\n"
            "  Drugs: Dasatinib (Phase III)\n"
            "  Mechanism: RTK inhibitor\n"
            "  Max phase: 3\n"
            "\n"
            "PubMed: 12 papers retrieved\n"
            "  Top: \u201cDDR1 in breast\n"
            "        cancer invasion\u2026\u201d\n"
            "  Quality: 0.88"
        ),
    },
    {
        "header": "Ranked Hypothesis",
        "body": (
            '#1 "CD4+ T cell trafficking\n'
            "    via HLA-DRB1\u2013ICAM1 drives\n"
            '    pro-fibrotic infiltration"\n'
            "  Category: Novel Pathway\n"
            "  UCB composite: 0.83\n"
            "    Evid: 0.90 | Spec: 0.80\n"
            "    Nov:  0.85 | Act:  0.75"
        ),
    },
    {
        "header": "Validated Report",
        "body": (
            "drug.md \u2014 3 featured genes\n"
            "  DDR1  (validated, 13)\n"
            "  MUC1  (exploratory, 10)\n"
            "  TGFB1 (validated, 11)\n"
            "\n"
            "validate_drug_md():\n"
            "  Fabricated PMIDs: 0\n"
            "  Issue count: 0 (pass)\n"
            "Quality gate: 0.82 > 0.70 \u2713"
        ),
    },
]


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def draw_rounded_rect(ax, x, y, w, h, fill, border, lw=1.5, radius=0.015):
    """Draw a rounded rectangle on the axes."""
    rect = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=fill, edgecolor=border, linewidth=lw,
        transform=ax.transAxes, zorder=2,
    )
    ax.add_patch(rect)
    return rect


def draw_arrow(ax, x0, y0, x1, y1, color=COLORS["arrow"], lw=1.8,
               style="-|>", linestyle="-"):
    """Draw an arrow between two points in axes coordinates."""
    arrow = FancyArrowPatch(
        (x0, y0), (x1, y1),
        arrowstyle=style, color=color, lw=lw,
        linestyle=linestyle,
        transform=ax.transAxes, zorder=3,
        mutation_scale=14,
    )
    ax.add_patch(arrow)


def draw_dashed_connector(ax, x0, y0, x1, y1):
    """Draw a thin dashed connector line."""
    ax.plot([x0, x1], [y0, y1],
            color=COLORS["dashed"], lw=0.8, linestyle="--",
            transform=ax.transAxes, zorder=1)


def wrap_text(text, max_chars=32):
    """Simple word-wrap for panel body text."""
    lines = []
    for line in text.split("\n"):
        if len(line) <= max_chars:
            lines.append(line)
        else:
            words = line.split(" ")
            current = ""
            for w in words:
                if len(current) + len(w) + 1 <= max_chars:
                    current = f"{current} {w}" if current else w
                else:
                    if current:
                        lines.append(current)
                    current = w
            if current:
                lines.append(current)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main figure builder
# ---------------------------------------------------------------------------

def build_figure(output_path: str, dpi: int = DPI):
    """Build the complete Medea-style Drug Target Agent figure."""

    fig, ax = plt.subplots(1, 1, figsize=(FIG_W, FIG_H), dpi=dpi)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    fig.patch.set_facecolor(COLORS["bg"])

    # --- Subtle center column background ---
    center_bg = FancyBboxPatch(
        (CENTER_X0 - 0.015, ROW_TOPS[3] - 0.035),
        (CENTER_X1 - CENTER_X0) + 0.03,
        (ROW_TOPS[0] + MODULE_H + 0.04) - (ROW_TOPS[3] - 0.035),
        boxstyle="round,pad=0,rounding_size=0.01",
        facecolor="#FAFAFA", edgecolor="none",
        transform=ax.transAxes, zorder=0,
    )
    ax.add_patch(center_bg)

    # --- Step numbers on left side of modules ---
    for idx, row_top in enumerate(ROW_TOPS):
        ax.text(CENTER_X0 + 0.012, row_top + MODULE_H / 2,
                str(idx + 1), fontsize=16, fontweight="bold",
                fontfamily="sans-serif", color="#E0E0E0",
                ha="center", va="center", transform=ax.transAxes, zorder=3)

    # --- Figure label ---
    ax.text(0.02, 0.98, "a", fontsize=18, fontweight="bold",
            fontfamily="sans-serif", transform=ax.transAxes, va="top")

    # --- Title ---
    ax.text(0.50, 0.975, "Drug Target Assessment Agent",
            fontsize=14, fontweight="bold", fontfamily="sans-serif",
            ha="center", va="top", transform=ax.transAxes,
            color="#212121")

    # --- Input arrow ---
    cx = (CENTER_X0 + CENTER_X1) / 2
    input_y = ROW_TOPS[0] + MODULE_H + 0.02
    draw_arrow(ax, cx, input_y + 0.015, cx, ROW_TOPS[0] + MODULE_H + 0.003)
    ax.text(cx, input_y + 0.02, "lr_candidates.json  +  disease context",
            fontsize=6.5, fontfamily="sans-serif", color=COLORS["arrow"],
            ha="center", va="bottom", transform=ax.transAxes)

    # --- Draw center modules ---
    for i, mod in enumerate(MODULES):
        row_top = ROW_TOPS[i]
        c = COLORS[mod["key"]]

        # Module box
        draw_rounded_rect(ax, CENTER_X0, row_top, CENTER_X1 - CENTER_X0,
                         MODULE_H, c["fill"], c["border"], lw=2.0)

        # Title
        ax.text(cx, row_top + MODULE_H - 0.015, mod["title"],
                fontsize=11, fontweight="bold", fontfamily="sans-serif",
                ha="center", va="top", color=c["text"],
                transform=ax.transAxes, zorder=4)

        # Subtitle
        ax.text(cx, row_top + MODULE_H - 0.04, mod["subtitle"],
                fontsize=6, fontfamily="sans-serif", fontstyle="italic",
                ha="center", va="top", color="#757575",
                transform=ax.transAxes, zorder=4)

        # Ribbon (internal stages)
        ribbon_y = row_top + 0.018
        # Ribbon background
        ribbon_rect = FancyBboxPatch(
            (CENTER_X0 + 0.015, ribbon_y - 0.003),
            (CENTER_X1 - CENTER_X0) - 0.03, 0.03,
            boxstyle="round,pad=0,rounding_size=0.006",
            facecolor="white", edgecolor=c["border"],
            linewidth=0.5, alpha=0.75,
            transform=ax.transAxes, zorder=3,
        )
        ax.add_patch(ribbon_rect)
        ax.text(cx, ribbon_y + 0.012, mod["ribbon"],
                fontsize=4.8, fontfamily="monospace",
                ha="center", va="center", color="#555555",
                transform=ax.transAxes, zorder=4)

        # Badge (top-right corner)
        ax.text(CENTER_X1 - 0.015, row_top + MODULE_H - 0.008,
                mod["badge"], fontsize=5, fontfamily="sans-serif",
                ha="right", va="top", color=c["border"],
                transform=ax.transAxes, zorder=4,
                bbox=dict(boxstyle="round,pad=0.12", facecolor="white",
                         edgecolor=c["border"], linewidth=0.4, alpha=0.85))

        # Arrow to next module
        if i < len(MODULES) - 1:
            next_top = ROW_TOPS[i + 1]
            draw_arrow(ax, cx, row_top - 0.005, cx, next_top + MODULE_H + 0.005)

    # --- Zero-candidate short-circuit arrow ---
    # Curved dashed arrow from Evidence Assessor right side to Report Writer right side
    sc_x_out = CENTER_X1 + 0.01
    sc_y0 = ROW_TOPS[0] + MODULE_H * 0.35
    sc_y1 = ROW_TOPS[3] + MODULE_H * 0.65
    ax.annotate("",
                xy=(sc_x_out, sc_y1), xytext=(sc_x_out, sc_y0),
                arrowprops=dict(arrowstyle="-|>", color="#BDBDBD",
                               lw=1.0, linestyle="--",
                               connectionstyle="arc3,rad=-0.25"),
                transform=ax.transAxes, zorder=1)
    ax.text(sc_x_out + 0.025, (sc_y0 + sc_y1) / 2, "zero\ncandidates",
            fontsize=5, fontfamily="sans-serif", color="#BDBDBD",
            ha="left", va="center",
            transform=ax.transAxes)

    # --- Output arrow ---
    output_y = ROW_TOPS[3] - 0.02
    draw_arrow(ax, cx, ROW_TOPS[3] - 0.003, cx, output_y - 0.008)
    ax.text(cx, output_y - 0.015,
            "drug.md   +   target_assessment.json   +   hypothesis_report.json",
            fontsize=5.5, fontfamily="sans-serif", color=COLORS["arrow"],
            ha="center", va="top", transform=ax.transAxes)

    # --- Draw side panels ---
    for i, (left, right) in enumerate(zip(LEFT_PANELS, RIGHT_PANELS)):
        row_top = ROW_TOPS[i]
        panel_top = row_top + (MODULE_H - PANEL_H) / 2  # vertically center

        # LEFT panel
        lx0 = LEFT_X0
        lw = LEFT_X1 - LEFT_X0
        draw_rounded_rect(ax, lx0, panel_top, lw, PANEL_H,
                         COLORS["panel"]["fill"], COLORS["panel"]["border"],
                         lw=0.7, radius=0.006)

        # Left panel header
        ax.text(lx0 + 0.008, panel_top + PANEL_H - 0.008, left["header"],
                fontsize=6, fontweight="bold", fontfamily="sans-serif",
                color="#333333", va="top", transform=ax.transAxes, zorder=4)

        # Header underline
        ax.plot([lx0 + 0.008, lx0 + lw - 0.008],
                [panel_top + PANEL_H - 0.022, panel_top + PANEL_H - 0.022],
                color="#E0E0E0", lw=0.5, transform=ax.transAxes, zorder=4)

        # Left panel body
        body = wrap_text(left["body"], max_chars=32)
        ax.text(lx0 + 0.008, panel_top + PANEL_H - 0.028, body,
                fontsize=4.5, fontfamily="monospace", color=COLORS["panel"]["text"],
                va="top", transform=ax.transAxes, zorder=4,
                linespacing=1.25)

        # Dashed connector: left panel right edge → center module left edge
        mid_y = row_top + MODULE_H / 2
        draw_dashed_connector(ax, LEFT_X1 + 0.002, mid_y,
                            CENTER_X0 - 0.002, mid_y)

        # RIGHT panel
        rx0 = RIGHT_X0
        rw = RIGHT_X1 - RIGHT_X0
        draw_rounded_rect(ax, rx0, panel_top, rw, PANEL_H,
                         COLORS["panel"]["fill"], COLORS["panel"]["border"],
                         lw=0.7, radius=0.006)

        # Right panel header
        ax.text(rx0 + 0.008, panel_top + PANEL_H - 0.008, right["header"],
                fontsize=6, fontweight="bold", fontfamily="sans-serif",
                color="#333333", va="top", transform=ax.transAxes, zorder=4)

        # Header underline
        ax.plot([rx0 + 0.008, rx0 + rw - 0.008],
                [panel_top + PANEL_H - 0.022, panel_top + PANEL_H - 0.022],
                color="#E0E0E0", lw=0.5, transform=ax.transAxes, zorder=4)

        # Right panel body
        body = wrap_text(right["body"], max_chars=32)
        ax.text(rx0 + 0.008, panel_top + PANEL_H - 0.028, body,
                fontsize=4.5, fontfamily="monospace", color=COLORS["panel"]["text"],
                va="top", transform=ax.transAxes, zorder=4,
                linespacing=1.25)

        # Dashed connector: center module right edge → right panel left edge
        draw_dashed_connector(ax, CENTER_X1 + 0.002, mid_y,
                            RIGHT_X0 - 0.002, mid_y)

    # --- Middleware annotation (bottom) ---
    mw_y = 0.05
    ax.text(cx, mw_y, "Middleware: WriteFileArgGuard  |  ReadFileBlock  |  SubagentErrorGuard",
            fontsize=5.5, fontfamily="sans-serif", color="#9E9E9E",
            ha="center", va="center", transform=ax.transAxes,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#FAFAFA",
                     edgecolor="#E0E0E0", linewidth=0.5))

    # --- Save ---
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=dpi, bbox_inches="tight", pad_inches=0.15,
                facecolor=COLORS["bg"])
    plt.close(fig)
    print(f"Saved: {output} ({dpi} DPI)")
    return str(output)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Drug Target Agent Medea-style figure")
    parser.add_argument("-o", "--output", default="fig/drug_target_figure_medea.png",
                       help="Output path (default: fig/drug_target_figure_medea.png)")
    parser.add_argument("--dpi", type=int, default=DPI,
                       help=f"DPI (default: {DPI})")
    args = parser.parse_args()
    build_figure(args.output, args.dpi)

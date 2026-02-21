"""HTML report generator tool for Deep Interpreter Agent.

This tool generates publication-quality HTML reports for CCI analysis
interpretations with dark theme styling and embedded figures.

CSS and JavaScript are loaded from external files in the skills directory,
with fallback to embedded content if files are not found.
"""

import base64
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool


# Path to skills assets directory
_SKILLS_ASSETS_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "skills"
    / "html-report-generator"
    / "assets"
)


def _load_css() -> str:
    """Load CSS from external file or return fallback.

    Loads theme.css from skills/html-report-generator/assets/ directory.
    Falls back to embedded minimal CSS if file is not found.

    Returns:
        CSS content as string
    """
    css_path = _SKILLS_ASSETS_DIR / "theme.css"
    if css_path.exists():
        try:
            return css_path.read_text(encoding="utf-8")
        except Exception:
            pass
    # Fallback CSS (minimal version for compatibility)
    return _FALLBACK_CSS


def _load_js() -> str:
    """Load JavaScript from external file or return fallback.

    Loads interactive.js from skills/html-report-generator/assets/ directory.
    Falls back to embedded JavaScript if file is not found.

    Returns:
        JavaScript content as string
    """
    js_path = _SKILLS_ASSETS_DIR / "interactive.js"
    if js_path.exists():
        try:
            return js_path.read_text(encoding="utf-8")
        except Exception:
            pass
    # Fallback JavaScript
    return _FALLBACK_JS


# Fallback CSS (embedded for when external file is not available)
_FALLBACK_CSS = """
:root {
    --color-primary: #64ffda;
    --color-secondary: #ffd166;
    --color-accent: #ff6b9d;
    --bg-primary: #1a1a2e;
    --bg-secondary: #16213e;
    --text-primary: #e4e4e4;
    --text-secondary: #aaa;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, var(--bg-primary) 0%, var(--bg-secondary) 100%); color: var(--text-primary); line-height: 1.6; padding: 20px; }
.container { max-width: 1400px; margin: 0 auto; background: rgba(26, 26, 46, 0.95); border-radius: 15px; box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5); padding: 40px; }
h1 { color: var(--color-primary); font-size: 2.5em; margin-bottom: 10px; text-align: center; text-shadow: 0 0 10px rgba(100, 255, 218, 0.5); }
.subtitle { text-align: center; color: var(--text-secondary); font-size: 1.2em; margin-bottom: 40px; font-style: italic; }
h2 { color: var(--color-primary); font-size: 2em; margin-top: 40px; margin-bottom: 20px; padding-bottom: 10px; border-bottom: 2px solid var(--color-primary); }
h3 { color: var(--color-secondary); font-size: 1.5em; margin-top: 30px; margin-bottom: 15px; }
h4 { color: var(--color-accent); font-size: 1.2em; margin-top: 20px; margin-bottom: 10px; }
.analysis-section { background: rgba(35, 35, 60, 0.6); padding: 25px; border-radius: 10px; margin-bottom: 30px; border-left: 4px solid var(--color-primary); }
.figure-container { text-align: center; margin: 30px 0; background: rgba(0, 0, 0, 0.3); padding: 20px; border-radius: 10px; }
.figure-container img { max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 5px 15px rgba(100, 255, 218, 0.3); }
.figure-caption { color: var(--text-secondary); font-style: italic; margin-top: 15px; font-size: 0.95em; }
.interpretation { background: rgba(100, 255, 218, 0.1); padding: 20px; border-left: 4px solid var(--color-primary); border-radius: 5px; margin: 20px 0; }
.interpretation h4 { color: var(--color-primary); margin-bottom: 10px; }
.key-findings { background: rgba(255, 107, 157, 0.1); padding: 20px; border-radius: 5px; margin: 20px 0; }
.key-findings ul { list-style-position: inside; margin-left: 20px; }
.key-findings li { margin: 10px 0; color: var(--text-primary); }
.summary-box { background: linear-gradient(135deg, rgba(100, 255, 218, 0.1) 0%, rgba(255, 107, 157, 0.1) 100%); padding: 25px; border-radius: 10px; margin: 30px 0; border: 2px solid rgba(100, 255, 218, 0.3); }
.tabs { display: flex; gap: 10px; margin: 20px 0; flex-wrap: wrap; border-bottom: 2px solid var(--color-primary); padding-bottom: 10px; }
.tab-button { background: rgba(35, 35, 60, 0.8); color: var(--color-primary); border: 2px solid var(--color-primary); padding: 12px 24px; cursor: pointer; border-radius: 5px 5px 0 0; transition: all 0.3s ease; font-size: 1.1em; font-weight: 500; }
.tab-button:hover { background: rgba(100, 255, 218, 0.2); transform: translateY(-2px); }
.tab-button.active { background: var(--color-primary); color: var(--bg-primary); font-weight: bold; }
.tab-content { display: none; animation: fadeIn 0.5s; }
.tab-content.active { display: block; }
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
.confidence-bar { background: rgba(100, 100, 100, 0.3); border-radius: 10px; height: 10px; margin: 5px 0; overflow: hidden; }
.confidence-fill { height: 100%; background: linear-gradient(90deg, var(--color-accent), var(--color-primary)); border-radius: 10px; }
.reference { color: var(--color-primary); text-decoration: none; font-weight: bold; }
.reference:hover { text-decoration: underline; }
table { width: 100%; border-collapse: collapse; margin: 20px 0; background: rgba(35, 35, 60, 0.6); border-radius: 8px; overflow: hidden; }
th { background: rgba(100, 255, 218, 0.2); color: var(--color-primary); padding: 12px; text-align: left; font-weight: bold; border-bottom: 2px solid var(--color-primary); }
td { padding: 10px 12px; border-bottom: 1px solid rgba(100, 255, 218, 0.1); }
tr:hover { background: rgba(100, 255, 218, 0.05); }
.table-container { overflow-x: auto; }
.score-badge { display: inline-block; padding: 3px 10px; border-radius: 15px; font-size: 0.85em; margin-left: 10px; }
.score-high { background: rgba(100, 255, 218, 0.3); color: var(--color-primary); }
.score-medium { background: rgba(255, 209, 102, 0.3); color: var(--color-secondary); }
.score-low { background: rgba(255, 107, 157, 0.3); color: var(--color-accent); }
.paper-card { background: rgba(30, 30, 50, 0.8); border-radius: 8px; padding: 15px; margin: 10px 0; border-left: 3px solid var(--color-primary); }
.paper-title a { color: var(--color-primary); text-decoration: none; }
.paper-title a:hover { text-decoration: underline; }
.highlight-cluster { color: var(--color-secondary); font-weight: bold; }
.highlight-pathway { color: var(--color-accent); font-weight: bold; }
.highlight-celltype { color: var(--color-primary); font-weight: bold; }
.pathway-box { background: rgba(255, 209, 102, 0.1); padding: 15px; border-radius: 5px; margin: 10px 0; border-left: 4px solid var(--color-secondary); }
.pathway-box ul { margin-left: 20px; margin-top: 10px; }
.pagination { display: flex; justify-content: center; gap: 10px; margin: 20px 0; }
.page-button { background: rgba(100, 255, 218, 0.2); color: var(--color-primary); border: 1px solid var(--color-primary); padding: 8px 16px; cursor: pointer; border-radius: 5px; transition: all 0.3s ease; }
.page-button:hover { background: rgba(100, 255, 218, 0.4); }
.page-button.active { background: var(--color-primary); color: var(--bg-primary); font-weight: bold; }
.interactions-page { display: none; }
.interactions-page.active { display: block; }
.metadata { color: #666; font-size: 0.9em; text-align: center; margin-top: 40px; padding-top: 20px; border-top: 1px solid rgba(100, 255, 218, 0.2); }
.drug-card { background: rgba(100, 200, 255, 0.1); border-left: 4px solid #64b5f6; border-radius: 8px; padding: 15px; margin: 10px 0; }
.drug-card h4 { color: #64b5f6; margin-bottom: 8px; }
.tractability-high { color: #64ffda; font-weight: bold; }
.tractability-low { color: #ff6b9d; font-style: italic; }
.drug-phase { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.85em; margin-left: 8px; }
.drug-phase-4 { background: rgba(100, 255, 218, 0.3); color: var(--color-primary); }
.drug-phase-3 { background: rgba(255, 209, 102, 0.3); color: var(--color-secondary); }
.drug-phase-2 { background: rgba(255, 107, 157, 0.2); color: var(--color-accent); }
.drug-phase-1 { background: rgba(150, 150, 150, 0.2); color: var(--text-secondary); }
.target-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px; margin: 20px 0; }
.novel-badge { display: inline-block; background: rgba(255, 209, 102, 0.3); color: var(--color-secondary); padding: 2px 10px; border-radius: 12px; font-size: 0.8em; margin-left: 8px; }
"""

# Fallback JavaScript (embedded for when external file is not available)
_FALLBACK_JS = """
function openTab(evt, tabName) {
    var i, tabcontent, tabbuttons;
    tabcontent = document.getElementsByClassName("tab-content");
    for (i = 0; i < tabcontent.length; i++) {
        tabcontent[i].style.display = "none";
        tabcontent[i].classList.remove("active");
    }
    tabbuttons = document.getElementsByClassName("tab-button");
    for (i = 0; i < tabbuttons.length; i++) {
        tabbuttons[i].classList.remove("active");
    }
    document.getElementById(tabName).style.display = "block";
    document.getElementById(tabName).classList.add("active");
    if (evt) {
        evt.currentTarget.classList.add("active");
    }
}

function showPage(pageNum) {
    var i, pages, buttons;
    pages = document.getElementsByClassName("interactions-page");
    for (i = 0; i < pages.length; i++) {
        pages[i].style.display = "none";
        pages[i].classList.remove("active");
    }
    buttons = document.getElementsByClassName("page-button");
    for (i = 0; i < buttons.length; i++) {
        buttons[i].classList.remove("active");
    }
    var targetPage = document.getElementById("interactions-page-" + pageNum);
    if (targetPage) {
        targetPage.style.display = "block";
        targetPage.classList.add("active");
    }
    if (buttons[pageNum - 1]) {
        buttons[pageNum - 1].classList.add("active");
    }
}

document.addEventListener('DOMContentLoaded', function() {
    openTab(null, 'part1');
    if (document.getElementById("interactions-page-1")) {
        showPage(1);
    }
});
"""

# HTML template with placeholders for CSS and JS
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
{css}
    </style>
</head>
<body>
    <div class="container">
        <button class="theme-toggle" onclick="toggleTheme()" title="Toggle light/dark theme">&#9681;</button>
        <h1>{title}</h1>
        <p class="subtitle">{subtitle}</p>

        <!-- Executive Summary -->
        <div class="summary-box">
            <h3>Executive Summary</h3>
            {executive_summary}
        </div>

        <!-- Analysis Configuration -->
        <div class="analysis-section">
            <h3>Analysis Configuration</h3>
            {analysis_config}
        </div>

        <!-- Tabs Navigation -->
        <div class="tabs">
            <button class="tab-button active" onclick="openTab(event, 'part1')">Part 1: Spatial & Pathway</button>
            <button class="tab-button" onclick="openTab(event, 'part2')">Part 2: CCI & NMF</button>
            <button class="tab-button" onclick="openTab(event, 'part3')">Part 3: L-R Interactions</button>
            <button class="tab-button" onclick="openTab(event, 'summary')">Comprehensive Summary</button>
            <button class="tab-button" onclick="openTab(event, 'therapeutic')">Therapeutic Implications</button>
        </div>

        <!-- Part 1 Content -->
        <div id="part1" class="tab-content active">
            {part1_content}
        </div>

        <!-- Part 2 Content -->
        <div id="part2" class="tab-content">
            {part2_content}
        </div>

        <!-- Part 3 Content -->
        <div id="part3" class="tab-content">
            {part3_content}
        </div>

        <!-- Summary Content -->
        <div id="summary" class="tab-content">
            {summary_content}
        </div>

        <!-- Therapeutic Implications Content -->
        <div id="therapeutic" class="tab-content">
            {therapeutic_content}
        </div>

        <!-- Metadata -->
        <div class="metadata">
            <p>Generated by DeepMAST Deep Interpreter (DeepAgents Framework)</p>
            <p>Date: {generation_date}</p>
        </div>
    </div>

    <script>
{js}
    </script>
</body>
</html>
"""


def _encode_image(image_path: str) -> Optional[str]:
    """Encode an image as Base64 data URI.

    Args:
        image_path: Path to the image file

    Returns:
        Base64 data URI string, or None if encoding fails
    """
    if not image_path or not os.path.exists(image_path):
        return None

    try:
        ext = Path(image_path).suffix.lower()
        mime_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
        }
        mime_type = mime_types.get(ext, "image/png")

        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        return f"data:{mime_type};base64,{image_data}"

    except Exception:
        return None


def _generate_figure_html(figure_path: Optional[str], caption: str) -> str:
    """Generate HTML for a figure with Base64 embedding.

    Args:
        figure_path: Path to the figure file
        caption: Figure caption

    Returns:
        HTML string for the figure
    """
    data_uri = _encode_image(figure_path) if figure_path else None

    if data_uri:
        return f"""
        <div class="figure-container">
            <img src="{data_uri}" alt="{caption}">
            <p class="figure-caption">{caption}</p>
        </div>
        """
    else:
        return f"""
        <div class="figure-container">
            <p style="color: #666; padding: 40px;">Figure not available</p>
            <p class="figure-caption">{caption}</p>
        </div>
        """


def _generate_interpretation_html(interpretation: str, title: str = "Biological Interpretation") -> str:
    """Generate HTML for an interpretation block.

    Args:
        interpretation: The interpretation text (can contain HTML)
        title: Block title

    Returns:
        HTML string
    """
    return f"""
    <div class="interpretation">
        <h4>{title}</h4>
        <div>{interpretation}</div>
    </div>
    """


def _generate_references_html(references: list[dict]) -> str:
    """Generate HTML for references section.

    Args:
        references: List of reference dictionaries with pmid, title,
            and optional authors, year fields

    Returns:
        HTML string
    """
    if not references:
        return ""

    # Ensure references is a list
    if not isinstance(references, list):
        return ""

    cards = []
    for ref in references:
        # Skip non-dict entries
        if not isinstance(ref, dict):
            continue
        pmid = ref.get("pmid", "")
        title = ref.get("title", f"Article {pmid}")
        authors = ref.get("authors", "")
        year = ref.get("year", "")

        # Format display: "Author et al. (Year) - Title" or just "Title"
        if authors and year:
            display_text = f"{authors} ({year}) - {title}"
        elif authors:
            display_text = f"{authors} - {title}"
        else:
            display_text = title

        cards.append(f"""
        <div class="paper-card">
            <div class="paper-title">
                <a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" target="_blank">{display_text}</a>
            </div>
        </div>
        """)

    return f"""
    <div class="key-findings">
        <h4>Supporting Literature</h4>
        {''.join(cards)}
    </div>
    """


def _generate_part_content(part_data: dict) -> str:
    """Generate HTML content for a part section from structured data.

    Args:
        part_data: Dictionary with analysis_name -> {figure_path, interpretation, caption, references}

    Returns:
        HTML string for the part content
    """
    if not part_data or not isinstance(part_data, dict):
        return "<p>No content available</p>"

    sections = []
    for analysis_name, analysis_data in part_data.items():
        # Ensure analysis_data is a dict
        if not isinstance(analysis_data, dict):
            analysis_data = {"interpretation": str(analysis_data) if analysis_data else ""}
        figure_path = analysis_data.get("figure_path")
        interpretation = analysis_data.get("interpretation", "")
        caption = analysis_data.get("caption", analysis_name)
        refs = analysis_data.get("references", [])
        if not isinstance(refs, list):
            refs = []

        sections.append(f"""
        <div class="analysis-section">
            <h3>{analysis_name}</h3>
            {_generate_figure_html(figure_path, caption)}
            {_generate_interpretation_html(interpretation)}
            {_generate_references_html(refs)}
        </div>
        """)

    return "\n".join(sections) if sections else "<p>No content available</p>"


def _generate_html_report_impl(
    parts: dict,
    output_path: str,
) -> str:
    """Internal implementation for HTML report generation.

    Args:
        parts: Dictionary containing report sections:
            Required fields:
            - title: Report title
            - subtitle: Report subtitle
            - executive_summary: Executive summary text (can contain HTML)
            - analysis_config: Analysis configuration details (can contain HTML)
            - part1: Dict with interpretations and figures for Part 1
            - part2: Dict with interpretations and figures for Part 2
            - part3: Dict with interpretations and figures for Part 3
            - synthesis: Synthesis narrative
            - quality_score: Overall quality score
            - references: List of reference dictionaries

            Optional fields (for LLM-generated HTML):
            - part1_html: LLM-generated HTML for Part 1 (overrides part1 dict)
            - part2_html: LLM-generated HTML for Part 2 (overrides part2 dict)
            - part3_html: LLM-generated HTML for Part 3 (overrides part3 dict)
            - summary_html: LLM-generated HTML for Summary (overrides synthesis)

        output_path: Path to save the HTML report

    Returns:
        String with report generation status and output path
    """
    # Extract parts with type validation
    title = parts.get("title", "CCI Analysis Report")
    subtitle = parts.get("subtitle", "Comprehensive Cell-Cell Interaction Analysis")
    executive_summary = parts.get("executive_summary", "")
    analysis_config = parts.get("analysis_config", "")

    # Convert dict analysis_config to HTML table
    if isinstance(analysis_config, dict):
        rows = "".join(
            f"<tr><td><strong>{k}</strong></td><td>{v}</td></tr>"
            for k, v in analysis_config.items()
        )
        analysis_config = f'<table class="analysis-config-table">{rows}</table>'

    # Validate part1, part2, part3 are dicts
    part1 = parts.get("part1", {})
    if not isinstance(part1, dict):
        part1 = {}

    part2 = parts.get("part2", {})
    if not isinstance(part2, dict):
        part2 = {}

    part3 = parts.get("part3", {})
    if not isinstance(part3, dict):
        part3 = {}

    synthesis = parts.get("synthesis", "")

    # Validate quality_score is numeric
    quality_score_raw = parts.get("quality_score", 0.0)
    try:
        quality_score = float(quality_score_raw) if quality_score_raw is not None else 0.0
    except (TypeError, ValueError):
        quality_score = 0.0

    # Validate references is a list
    references = parts.get("references", [])
    if not isinstance(references, list):
        references = []

    # Check for LLM-generated HTML overrides (backward compatible)
    part1_html = parts.get("part1_html")
    part2_html = parts.get("part2_html")
    part3_html = parts.get("part3_html")
    summary_html = parts.get("summary_html")
    therapeutic_html = parts.get("therapeutic_html")

    # Build executive summary HTML
    # If executive_summary already contains HTML tags, use it directly
    if "<" in executive_summary and ">" in executive_summary:
        exec_summary_html = executive_summary
    else:
        # Generate from plain text
        score_class = "score-high" if quality_score >= 0.7 else "score-medium" if quality_score >= 0.5 else "score-low"
        exec_summary_html = f"""
        <p>{executive_summary}</p>
        <div class="key-findings">
            <h4>Quality Metrics</h4>
            <ul>
                <li><strong>Quality Score:</strong> <span class="score-badge {score_class}">{quality_score:.2f}</span></li>
            </ul>
        </div>
        """

    # Build Part 1 content: HTML override or structured data
    if part1_html:
        part1_content = part1_html
    else:
        part1_content = _generate_part_content(part1)

    # Build Part 2 content: HTML override or structured data
    if part2_html:
        part2_content = part2_html
    else:
        part2_content = _generate_part_content(part2)

    # Build Part 3 content: HTML override or structured data
    if part3_html:
        part3_content = part3_html
    else:
        part3_content = _generate_part_content(part3)

    # Build summary content: HTML override or structured data
    if summary_html:
        summary_content = summary_html
    else:
        score_class = "score-high" if quality_score >= 0.7 else "score-medium" if quality_score >= 0.5 else "score-low"
        summary_content = f"""
        <div class="analysis-section">
            <h3>Integrated Biological Narrative</h3>
            <div class="interpretation">
                <div>{synthesis}</div>
            </div>
        </div>
        <div class="analysis-section">
            <h3>Quality Assessment</h3>
            <div class="summary-box">
                <h4>Overall Quality Score: <span class="score-badge {score_class}">{quality_score:.2f}</span></h4>
                <div class="confidence-bar">
                    <div class="confidence-fill" style="width: {quality_score * 100}%"></div>
                </div>
            </div>
        </div>
        {_generate_references_html(references)}
        """

    # Build therapeutic content: HTML override or structured data or empty
    if therapeutic_html:
        therapeutic_content = therapeutic_html
    else:
        therapeutic_data = parts.get("therapeutic")
        if therapeutic_data and isinstance(therapeutic_data, dict):
            # Build from structured therapeutic data
            druggable = therapeutic_data.get("druggable_targets", [])
            drugs = therapeutic_data.get("known_drugs", [])
            novel = therapeutic_data.get("novel_targets", [])
            summary = therapeutic_data.get("summary", {})

            druggable_html = ""
            if druggable:
                cards = []
                for t in druggable[:10]:
                    tract = t.get("tractability", {})
                    modalities = ", ".join(
                        f"{k}: {', '.join(v)}" for k, v in tract.items() if v
                    )
                    assoc = t.get("association_score", 0)
                    score_cls = "tractability-high" if assoc > 0.5 else "tractability-low"
                    cards.append(f"""
                    <div class="drug-card">
                        <h4>{t.get('gene', '')} <small>({t.get('name', '')})</small></h4>
                        <p><strong>Association Score:</strong> <span class="{score_cls}">{assoc:.3f}</span></p>
                        <p><strong>Tractability:</strong> {modalities or 'N/A'}</p>
                        <p><strong>Evidence Count:</strong> {t.get('evidence_count', 0)}</p>
                        <p><strong>Safety Concerns:</strong> {t.get('safety_concerns', 0)}</p>
                        <p><strong>L-R Frequency:</strong> {t.get('lr_frequency', 0)} (roles: {', '.join(t.get('lr_roles', []))})</p>
                    </div>
                    """)
                druggable_html = f"""
                <div class="analysis-section">
                    <h3>Druggable Targets ({len(druggable)} found)</h3>
                    <div class="target-grid">{''.join(cards)}</div>
                </div>
                """

            drugs_html = ""
            if drugs:
                rows = []
                for d in drugs[:20]:
                    phase = d.get("phase", 0)
                    phase_cls = f"drug-phase-{min(phase, 4)}"
                    rows.append(f"""
                    <tr>
                        <td>{d.get('drug_name', '')}</td>
                        <td><span class="drug-phase {phase_cls}">Phase {phase}</span></td>
                        <td>{d.get('mechanism_of_action', 'N/A')}</td>
                        <td>{', '.join(d.get('target_genes', []))}</td>
                        <td>{d.get('status', '')}</td>
                    </tr>
                    """)
                drugs_html = f"""
                <div class="analysis-section">
                    <h3>Known Drugs ({len(drugs)} found)</h3>
                    <div class="table-container">
                        <table>
                            <thead><tr><th>Drug</th><th>Phase</th><th>Mechanism</th><th>Targets</th><th>Status</th></tr></thead>
                            <tbody>{''.join(rows)}</tbody>
                        </table>
                    </div>
                </div>
                """

            novel_html = ""
            if novel:
                items = "".join(
                    f"<li><strong>{t.get('gene', '')}</strong> ({t.get('name', '')})"
                    f" <span class='novel-badge'>Novel</span>"
                    f" - L-R frequency: {t.get('lr_frequency', 0)}</li>"
                    for t in novel[:10]
                )
                novel_html = f"""
                <div class="analysis-section">
                    <h3>Novel Drug Target Candidates <span class="novel-badge">{len(novel)} found</span></h3>
                    <p>These genes are druggable but lack known disease associations — potential repurposing or novel target opportunities.</p>
                    <ul class="key-findings">{items}</ul>
                </div>
                """

            therapeutic_content = f"""
            <div class="summary-box">
                <h3>Therapeutic Potential Summary</h3>
                <p><strong>Genes Evaluated:</strong> {summary.get('total_genes_evaluated', 0)} |
                   <strong>Druggable:</strong> {summary.get('druggable_count', 0)} |
                   <strong>Known Drugs:</strong> {summary.get('known_drugs_count', 0)} |
                   <strong>Novel Targets:</strong> {summary.get('novel_target_count', 0)}</p>
            </div>
            {druggable_html}
            {drugs_html}
            {novel_html}
            """
        elif therapeutic_data and isinstance(therapeutic_data, str):
            therapeutic_content = f'<div class="analysis-section"><div class="interpretation"><div>{therapeutic_data}</div></div></div>'
        else:
            therapeutic_content = '<div class="analysis-section"><p style="color: #888;">No therapeutic analysis available. Run the Drug Target Assessment phase to populate this section.</p></div>'

    # Load CSS and JavaScript (from external files or fallback)
    css_content = _load_css()
    js_content = _load_js()

    # Fill template
    html = HTML_TEMPLATE.format(
        title=title,
        subtitle=subtitle,
        css=css_content,
        js=js_content,
        executive_summary=exec_summary_html,
        analysis_config=analysis_config,
        part1_content=part1_content,
        part2_content=part2_content,
        part3_content=part3_content,
        summary_content=summary_content,
        therapeutic_content=therapeutic_content,
        generation_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    # Write to file
    try:
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        return f"Report generated successfully: {output_path} ({len(html)} bytes)"

    except Exception as e:
        return f"Error generating report: {e}"


@tool
def generate_html_report(
    parts: dict,
    output_path: str,
    data_dir: str = "",
) -> str:
    """Generate a comprehensive HTML report for CCI analysis.

    This tool creates a publication-quality HTML report with dark theme,
    embedded figures, and organized interpretation sections.

    The report supports two modes:
    1. Structured mode: Provide part1/part2/part3 dicts with figure_path, interpretation, etc.
    2. HTML override mode: Provide part1_html/part2_html/part3_html with LLM-generated HTML

    CSS classes available for LLM-generated HTML:
    - .highlight-cluster: Yellow highlighting for cluster names
    - .highlight-pathway: Pink highlighting for pathway names
    - .highlight-celltype: Cyan highlighting for cell type names
    - .pathway-box: Yellow-bordered box for pathway descriptions
    - .key-findings: Pink-bordered box for key findings lists
    - .interpretation: Cyan-bordered box for interpretations
    - .analysis-section: Section container with cyan border
    - .pagination, .page-button: Pagination controls for tables
    - .interactions-page: Container for paginated content (use id="interactions-page-N")

    Args:
        parts: Dictionary containing report sections:
            Required fields:
            - title: Report title
            - subtitle: Report subtitle
            - executive_summary: Executive summary text (HTML allowed)
            - analysis_config: Analysis configuration details (HTML allowed)
            - part1: Dict with {analysis_name: {figure_path, interpretation, caption, references}}
            - part2: Dict with Part 2 analyses
            - part3: Dict with Part 3 analyses
            - synthesis: Synthesis narrative
            - quality_score: Overall quality score (0.0-1.0)
            - references: List of {pmid, title} dictionaries

            Optional HTML override fields:
            - part1_html: Complete HTML for Part 1 tab (overrides part1)
            - part2_html: Complete HTML for Part 2 tab (overrides part2)
            - part3_html: Complete HTML for Part 3 tab (overrides part3)
            - summary_html: Complete HTML for Summary tab (overrides synthesis)
            - therapeutic_html: Complete HTML for Therapeutic Implications tab
            - therapeutic: Dict with druggable_targets, known_drugs, novel_targets, summary

        output_path: Path to save the HTML report
        data_dir: Directory for saving the report. If output_path is relative,
            resolves to data_dir/output_path. Read from /data_path.txt (written by PLANNER).
            Falls back to contextvars if empty.

    Returns:
        String with report generation status and output path
    """
    # Resolve output_path with data_dir (fallback to context var)
    if not os.path.isabs(output_path):
        save_dir = data_dir or os.getenv("DEEP_INTERPRETER_DATA_DIR", "")
        if save_dir:
            save_dir = str(Path(save_dir).expanduser().resolve())
            output_path = os.path.join(save_dir, output_path)
    return _generate_html_report_impl(parts=parts, output_path=output_path)


def generate_simple_report(
    title: str,
    content: dict,
    output_path: str,
) -> str:
    """Generate a simplified HTML report.

    Args:
        title: Report title
        content: Dictionary with section content
        output_path: Output file path

    Returns:
        Status message
    """
    parts = {
        "title": title,
        "subtitle": content.get("subtitle", ""),
        "executive_summary": content.get("summary", ""),
        "analysis_config": content.get("config", ""),
        "part1": content.get("part1", {}),
        "part2": content.get("part2", {}),
        "part3": content.get("part3", {}),
        "synthesis": content.get("synthesis", ""),
        "quality_score": content.get("quality_score", 0.0),
        "references": content.get("references", []),
        # Forward HTML overrides if present
        "part1_html": content.get("part1_html"),
        "part2_html": content.get("part2_html"),
        "part3_html": content.get("part3_html"),
        "summary_html": content.get("summary_html"),
        "therapeutic_html": content.get("therapeutic_html"),
        "therapeutic": content.get("therapeutic"),
    }

    return _generate_html_report_impl(parts=parts, output_path=output_path)

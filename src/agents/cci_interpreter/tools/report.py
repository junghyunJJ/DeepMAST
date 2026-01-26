"""HTML report generator tool for CCI Interpreter Agent.

This tool generates publication-quality HTML reports for CCI analysis
interpretations with dark theme styling and embedded figures.
"""

import base64
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool


# HTML template with dark theme styling (matching existing report style)
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e4e4e4;
            line-height: 1.6;
            padding: 20px;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: rgba(26, 26, 46, 0.95);
            border-radius: 15px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
            padding: 40px;
        }}

        h1 {{
            color: #64ffda;
            font-size: 2.5em;
            margin-bottom: 10px;
            text-align: center;
            text-shadow: 0 0 10px rgba(100, 255, 218, 0.5);
        }}

        .subtitle {{
            text-align: center;
            color: #aaa;
            font-size: 1.2em;
            margin-bottom: 40px;
            font-style: italic;
        }}

        h2 {{
            color: #64ffda;
            font-size: 2em;
            margin-top: 40px;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #64ffda;
        }}

        h3 {{
            color: #ffd166;
            font-size: 1.5em;
            margin-top: 30px;
            margin-bottom: 15px;
        }}

        h4 {{
            color: #ff6b9d;
            font-size: 1.2em;
            margin-top: 20px;
            margin-bottom: 10px;
        }}

        .analysis-section {{
            background: rgba(35, 35, 60, 0.6);
            padding: 25px;
            border-radius: 10px;
            margin-bottom: 30px;
            border-left: 4px solid #64ffda;
        }}

        .figure-container {{
            text-align: center;
            margin: 30px 0;
            background: rgba(0, 0, 0, 0.3);
            padding: 20px;
            border-radius: 10px;
        }}

        .figure-container img {{
            max-width: 100%;
            height: auto;
            border-radius: 8px;
            box-shadow: 0 5px 15px rgba(100, 255, 218, 0.3);
        }}

        .figure-caption {{
            color: #aaa;
            font-style: italic;
            margin-top: 15px;
            font-size: 0.95em;
        }}

        .interpretation {{
            background: rgba(100, 255, 218, 0.1);
            padding: 20px;
            border-left: 4px solid #64ffda;
            border-radius: 5px;
            margin: 20px 0;
        }}

        .interpretation h4 {{
            color: #64ffda;
            margin-bottom: 10px;
        }}

        .key-findings {{
            background: rgba(255, 107, 157, 0.1);
            padding: 20px;
            border-radius: 5px;
            margin: 20px 0;
        }}

        .key-findings ul {{
            list-style-position: inside;
            margin-left: 20px;
        }}

        .key-findings li {{
            margin: 10px 0;
            color: #e4e4e4;
        }}

        .summary-box {{
            background: linear-gradient(135deg, rgba(100, 255, 218, 0.1) 0%, rgba(255, 107, 157, 0.1) 100%);
            padding: 25px;
            border-radius: 10px;
            margin: 30px 0;
            border: 2px solid rgba(100, 255, 218, 0.3);
        }}

        .tabs {{
            display: flex;
            gap: 10px;
            margin: 20px 0;
            flex-wrap: wrap;
            border-bottom: 2px solid #64ffda;
            padding-bottom: 10px;
        }}

        .tab-button {{
            background: rgba(35, 35, 60, 0.8);
            color: #64ffda;
            border: 2px solid #64ffda;
            padding: 12px 24px;
            cursor: pointer;
            border-radius: 5px 5px 0 0;
            transition: all 0.3s ease;
            font-size: 1.1em;
            font-weight: 500;
        }}

        .tab-button:hover {{
            background: rgba(100, 255, 218, 0.2);
            transform: translateY(-2px);
        }}

        .tab-button.active {{
            background: rgba(100, 255, 218, 0.3);
            border-bottom-color: transparent;
        }}

        .tab-content {{
            display: none;
            padding: 20px 0;
        }}

        .tab-content.active {{
            display: block;
        }}

        .confidence-bar {{
            background: rgba(100, 100, 100, 0.3);
            border-radius: 10px;
            height: 10px;
            margin: 5px 0;
            overflow: hidden;
        }}

        .confidence-fill {{
            height: 100%;
            background: linear-gradient(90deg, #ff6b9d, #64ffda);
            border-radius: 10px;
        }}

        .reference {{
            color: #64ffda;
            text-decoration: none;
            font-weight: bold;
        }}

        .reference:hover {{
            text-decoration: underline;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            background: rgba(35, 35, 60, 0.6);
            border-radius: 8px;
            overflow: hidden;
        }}

        th {{
            background: rgba(100, 255, 218, 0.2);
            color: #64ffda;
            padding: 12px;
            text-align: left;
            font-weight: bold;
            border-bottom: 2px solid #64ffda;
        }}

        td {{
            padding: 10px 12px;
            border-bottom: 1px solid rgba(100, 255, 218, 0.1);
        }}

        tr:hover {{
            background: rgba(100, 255, 218, 0.05);
        }}

        .score-badge {{
            display: inline-block;
            padding: 3px 10px;
            border-radius: 15px;
            font-size: 0.85em;
            margin-left: 10px;
        }}

        .score-high {{
            background: rgba(100, 255, 218, 0.3);
            color: #64ffda;
        }}

        .score-medium {{
            background: rgba(255, 209, 102, 0.3);
            color: #ffd166;
        }}

        .score-low {{
            background: rgba(255, 107, 157, 0.3);
            color: #ff6b9d;
        }}

        .paper-card {{
            background: rgba(30, 30, 50, 0.8);
            border-radius: 8px;
            padding: 15px;
            margin: 10px 0;
            border-left: 3px solid #64ffda;
        }}

        .paper-title a {{
            color: #64ffda;
            text-decoration: none;
        }}

        .paper-title a:hover {{
            text-decoration: underline;
        }}

        .metadata {{
            color: #666;
            font-size: 0.9em;
            text-align: center;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid rgba(100, 255, 218, 0.2);
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>
        <p class="subtitle">{subtitle}</p>

        <!-- Executive Summary -->
        <div class="summary-box">
            <h2>Executive Summary</h2>
            {executive_summary}
        </div>

        <!-- Analysis Configuration -->
        <div class="analysis-section">
            <h3>Analysis Configuration</h3>
            {analysis_config}
        </div>

        <!-- Tabs Navigation -->
        <div class="tabs">
            <button class="tab-button active" onclick="showTab('part1')">Part 1: Spatial & Pathway</button>
            <button class="tab-button" onclick="showTab('part2')">Part 2: CCI & NMF</button>
            <button class="tab-button" onclick="showTab('part3')">Part 3: L-R Interactions</button>
            <button class="tab-button" onclick="showTab('summary')">Comprehensive Summary</button>
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

        <!-- Metadata -->
        <div class="metadata">
            <p>Generated by DeepMAST CCI Interpreter (Deep Agents)</p>
            <p>Date: {generation_date}</p>
        </div>
    </div>

    <script>
        function showTab(tabId) {{
            document.querySelectorAll('.tab-content').forEach(content => {{
                content.classList.remove('active');
            }});
            document.querySelectorAll('.tab-button').forEach(btn => {{
                btn.classList.remove('active');
            }});
            document.getElementById(tabId).classList.add('active');
            event.target.classList.add('active');
        }}
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
        interpretation: The interpretation text
        title: Block title

    Returns:
        HTML string
    """
    return f"""
    <div class="interpretation">
        <h4>{title}</h4>
        <p>{interpretation}</p>
    </div>
    """


def _generate_references_html(references: list[dict]) -> str:
    """Generate HTML for references section.

    Args:
        references: List of reference dictionaries with pmid, title

    Returns:
        HTML string
    """
    if not references:
        return ""

    cards = []
    for ref in references[:5]:
        pmid = ref.get("pmid", "")
        title = ref.get("title", f"Article {pmid}")
        cards.append(f"""
        <div class="paper-card">
            <div class="paper-title">
                <a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" target="_blank">{title}</a>
            </div>
        </div>
        """)

    return f"""
    <div class="key-findings">
        <h4>Supporting Literature</h4>
        {''.join(cards)}
    </div>
    """


@tool
def generate_html_report(
    parts: dict,
    output_path: str,
) -> str:
    """Generate a comprehensive HTML report for CCI analysis.

    This tool creates a publication-quality HTML report with dark theme,
    embedded figures, and organized interpretation sections.

    Args:
        parts: Dictionary containing report sections:
            - title: Report title
            - subtitle: Report subtitle
            - executive_summary: Executive summary text
            - analysis_config: Analysis configuration details
            - part1: Dict with interpretations and figures for Part 1
            - part2: Dict with interpretations and figures for Part 2
            - part3: Dict with interpretations and figures for Part 3
            - synthesis: Synthesis narrative
            - quality_score: Overall quality score
            - references: List of reference dictionaries
        output_path: Path to save the HTML report

    Returns:
        String with report generation status and output path
    """
    # Extract parts
    title = parts.get("title", "CCI Analysis Report")
    subtitle = parts.get("subtitle", "Comprehensive Cell-Cell Interaction Analysis")
    executive_summary = parts.get("executive_summary", "")
    analysis_config = parts.get("analysis_config", "")
    part1 = parts.get("part1", {})
    part2 = parts.get("part2", {})
    part3 = parts.get("part3", {})
    synthesis = parts.get("synthesis", "")
    quality_score = parts.get("quality_score", 0.0)
    references = parts.get("references", [])

    # Build executive summary HTML
    score_class = "score-high" if quality_score >= 0.7 else "score-medium" if quality_score >= 0.5 else "score-low"
    exec_summary_html = f"""
    <div class="key-findings">
        <h4>Key Metrics</h4>
        <ul>
            <li><strong>Quality Score:</strong> <span class="score-badge {score_class}">{quality_score:.2f}</span></li>
        </ul>
    </div>
    <div class="interpretation">
        <p>{executive_summary}</p>
    </div>
    """

    # Build Part 1 content
    part1_sections = []
    for analysis_name, analysis_data in part1.items():
        figure_path = analysis_data.get("figure_path")
        interpretation = analysis_data.get("interpretation", "")
        caption = analysis_data.get("caption", analysis_name)
        refs = analysis_data.get("references", [])

        part1_sections.append(f"""
        <div class="analysis-section">
            <h3>{analysis_name}</h3>
            {_generate_figure_html(figure_path, caption)}
            {_generate_interpretation_html(interpretation)}
            {_generate_references_html(refs)}
        </div>
        """)

    part1_content = "\n".join(part1_sections) if part1_sections else "<p>No Part 1 content available</p>"

    # Build Part 2 content
    part2_sections = []
    for analysis_name, analysis_data in part2.items():
        figure_path = analysis_data.get("figure_path")
        interpretation = analysis_data.get("interpretation", "")
        caption = analysis_data.get("caption", analysis_name)
        refs = analysis_data.get("references", [])

        part2_sections.append(f"""
        <div class="analysis-section">
            <h3>{analysis_name}</h3>
            {_generate_figure_html(figure_path, caption)}
            {_generate_interpretation_html(interpretation)}
            {_generate_references_html(refs)}
        </div>
        """)

    part2_content = "\n".join(part2_sections) if part2_sections else "<p>No Part 2 content available</p>"

    # Build Part 3 content
    part3_sections = []
    for analysis_name, analysis_data in part3.items():
        figure_path = analysis_data.get("figure_path")
        interpretation = analysis_data.get("interpretation", "")
        caption = analysis_data.get("caption", analysis_name)
        refs = analysis_data.get("references", [])

        part3_sections.append(f"""
        <div class="analysis-section">
            <h3>{analysis_name}</h3>
            {_generate_figure_html(figure_path, caption)}
            {_generate_interpretation_html(interpretation)}
            {_generate_references_html(refs)}
        </div>
        """)

    part3_content = "\n".join(part3_sections) if part3_sections else "<p>No Part 3 content available</p>"

    # Build summary content
    summary_content = f"""
    <div class="analysis-section">
        <h3>Integrated Biological Narrative</h3>
        <div class="interpretation">
            <p>{synthesis}</p>
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

    # Fill template
    html = HTML_TEMPLATE.format(
        title=title,
        subtitle=subtitle,
        executive_summary=exec_summary_html,
        analysis_config=analysis_config,
        part1_content=part1_content,
        part2_content=part2_content,
        part3_content=part3_content,
        summary_content=summary_content,
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
    }

    return generate_html_report.invoke({"parts": parts, "output_path": output_path})

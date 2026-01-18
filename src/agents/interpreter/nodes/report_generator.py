"""HTML report generator for Biological Interpreter Agent.

This module generates a comprehensive HTML report with dark theme
containing all analysis interpretations and visualizations.
"""

from typing import Any
from datetime import datetime

from langchain_core.language_models.chat_models import BaseChatModel

from src.agents.interpreter.biological_interpreter_state import (
    BiologicalInterpreterState,
)


# HTML template with dark theme styling
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

        .claim-box {{
            background: rgba(255, 209, 102, 0.1);
            padding: 15px;
            border-radius: 5px;
            margin: 15px 0;
            border-left: 3px solid #ffd166;
        }}

        .claim-content {{
            font-weight: bold;
            margin-bottom: 10px;
        }}

        .claim-evidence {{
            color: #aaa;
            font-size: 0.9em;
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

        .pathway-desc {{
            display: grid;
            grid-template-columns: 150px 1fr;
            gap: 10px;
            margin: 5px 0;
            padding: 8px;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 5px;
        }}

        .pathway-name {{
            color: #ffd166;
            font-weight: bold;
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

        <!-- Analysis Mode Info -->
        <div class="analysis-section">
            <h3>Analysis Configuration</h3>
            {analysis_config}
        </div>

        <!-- Tabs Navigation -->
        <div class="tabs">
            <button class="tab-button active" onclick="showTab('part1')">Part 1: Before CCI</button>
            <button class="tab-button" onclick="showTab('part2')">Part 2: CCI + NMF</button>
            <button class="tab-button" onclick="showTab('part3')">Part 3: L-R Visualization</button>
            <button class="tab-button" onclick="showTab('synthesis')">Synthesis</button>
            <button class="tab-button" onclick="showTab('claims')">Claims & Evidence</button>
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

        <!-- Synthesis Content -->
        <div id="synthesis" class="tab-content">
            {synthesis_content}
        </div>

        <!-- Claims Content -->
        <div id="claims" class="tab-content">
            {claims_content}
        </div>

        <!-- Metadata -->
        <div class="metadata">
            <p>Generated by DeepMAST Biological Interpreter Agent</p>
            <p>Date: {generation_date}</p>
        </div>
    </div>

    <script>
        function showTab(tabId) {{
            // Hide all tab contents
            document.querySelectorAll('.tab-content').forEach(content => {{
                content.classList.remove('active');
            }});

            // Remove active class from all buttons
            document.querySelectorAll('.tab-button').forEach(btn => {{
                btn.classList.remove('active');
            }});

            // Show selected tab content
            document.getElementById(tabId).classList.add('active');

            // Add active class to clicked button
            event.target.classList.add('active');
        }}
    </script>
</body>
</html>
"""


async def generate_html_report(
    state: BiologicalInterpreterState,
    model: BaseChatModel,
    is_debug: bool = False,
) -> str:
    """Generate comprehensive HTML report.

    Args:
        state: Current agent state with all interpretations
        model: LLM (not used directly in report generation)
        is_debug: Debug flag

    Returns:
        Complete HTML report string
    """
    # Gather all required data
    analysis_mode = state.get("analysis_mode", "unknown")
    interest_clusters = state.get("interest_clusters", [])
    interest_celltypes = state.get("interest_celltypes", [])
    selected_celltypes = state.get("selected_celltypes", [])
    selected_clusters = state.get("selected_clusters", [])
    selected_pathways = state.get("selected_pathways", [])
    selected_factor = state.get("selected_factor", "")
    selected_lr_pairs = state.get("selected_lr_pairs", [])

    part1_results = state.get("part1_results", {})
    part2_results = state.get("part2_results", {})
    part1_interps = state.get("part1_interpretations", {})
    part2_interps = state.get("part2_interpretations", {})
    part3_interps = state.get("part3_interpretations", {})

    narrative = state.get("integrated_narrative", "")
    claims = state.get("claims", [])
    literature_evidence = state.get("literature_evidence", {})
    reflection_result = state.get("reflection_result", {})

    # Generate sections
    title = "Cell-Cell Interaction Analysis Report"
    subtitle = f"Analysis Mode: {'Cluster → Cell Type' if analysis_mode == 'cluster_to_celltype' else 'Cell Type → Cluster'}"

    executive_summary = generate_executive_summary(
        narrative=narrative,
        selected_lr_pairs=selected_lr_pairs,
        selected_pathways=selected_pathways,
        reflection_result=reflection_result,
    )

    analysis_config = generate_analysis_config(
        analysis_mode=analysis_mode,
        interest_clusters=interest_clusters,
        interest_celltypes=interest_celltypes,
        selected_celltypes=selected_celltypes,
        selected_clusters=selected_clusters,
    )

    part1_content = generate_part1_content(
        part1_results=part1_results,
        part1_interps=part1_interps,
        selected_pathways=selected_pathways,
    )

    part2_content = generate_part2_content(
        part2_results=part2_results,
        part2_interps=part2_interps,
        selected_factor=selected_factor,
        selected_lr_pairs=selected_lr_pairs,
        state=state,
    )

    part3_content = generate_part3_content(
        part2_results=part2_results,  # Part3 figures stored in part2_results
        part3_interps=part3_interps,
        selected_lr_pairs=selected_lr_pairs,
    )

    synthesis_content = generate_synthesis_content(
        narrative=narrative,
        reflection_result=reflection_result,
    )

    claims_content = generate_claims_content(
        claims=claims,
        literature_evidence=literature_evidence,
    )

    # Fill template
    html = HTML_TEMPLATE.format(
        title=title,
        subtitle=subtitle,
        executive_summary=executive_summary,
        analysis_config=analysis_config,
        part1_content=part1_content,
        part2_content=part2_content,
        part3_content=part3_content,
        synthesis_content=synthesis_content,
        claims_content=claims_content,
        generation_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    if is_debug:
        print(f"Generated HTML report ({len(html)} chars)")

    return html


def generate_executive_summary(
    narrative: str,
    selected_lr_pairs: list[str],
    selected_pathways: list[str],
    reflection_result: dict,
) -> str:
    """Generate executive summary section."""
    # Extract first paragraph from narrative
    summary_text = narrative[:500] + "..." if len(narrative) > 500 else narrative

    quality_score = (
        reflection_result.get("biological_plausibility_score", 0) +
        reflection_result.get("evidence_coverage_score", 0) +
        reflection_result.get("cross_part_consistency_score", 0)
    ) / 3

    score_class = "score-high" if quality_score >= 0.7 else "score-medium" if quality_score >= 0.5 else "score-low"

    html = f"""
    <div class="key-findings">
        <h4>Key Findings</h4>
        <ul>
            <li><strong>Selected L-R Pairs:</strong> {', '.join(selected_lr_pairs[:3]) if selected_lr_pairs else 'None'}</li>
            <li><strong>Key Pathways:</strong> {', '.join(selected_pathways[:5]) if selected_pathways else 'None'}</li>
            <li><strong>Quality Score:</strong> <span class="score-badge {score_class}">{quality_score:.2f}</span></li>
        </ul>
    </div>
    <div class="interpretation">
        <h4>Summary</h4>
        <p>{summary_text}</p>
    </div>
    """
    return html


def generate_analysis_config(
    analysis_mode: str,
    interest_clusters: list,
    interest_celltypes: list,
    selected_celltypes: list,
    selected_clusters: list,
) -> str:
    """Generate analysis configuration section."""
    mode_display = "Cluster → Cell Type" if analysis_mode == "cluster_to_celltype" else "Cell Type → Cluster"

    html = f"""
    <table>
        <tr>
            <th>Parameter</th>
            <th>Value</th>
        </tr>
        <tr>
            <td>Analysis Mode</td>
            <td>{mode_display}</td>
        </tr>
        <tr>
            <td>Input Clusters</td>
            <td>{', '.join(str(c) for c in interest_clusters) if interest_clusters else 'N/A'}</td>
        </tr>
        <tr>
            <td>Input Cell Types</td>
            <td>{', '.join(interest_celltypes) if interest_celltypes else 'N/A'}</td>
        </tr>
        <tr>
            <td>Derived Cell Types</td>
            <td>{', '.join(selected_celltypes) if selected_celltypes else 'N/A'}</td>
        </tr>
        <tr>
            <td>Derived Clusters</td>
            <td>{', '.join(str(c) for c in selected_clusters) if selected_clusters else 'N/A'}</td>
        </tr>
    </table>
    """
    return html


def generate_part1_content(
    part1_results: dict,
    part1_interps: dict,
    selected_pathways: list[str],
) -> str:
    """Generate Part 1 content with figures and interpretations."""
    sections = []

    # Part 1-1: Spatial
    spatial = part1_results.get("spatial", {})
    sections.append(f"""
    <div class="analysis-section">
        <h3>1-1. Spatial Clustering Analysis</h3>
        {generate_figure_html(spatial.get('figure_path'), 'Spatial distribution of clusters')}
        <div class="interpretation">
            <h4>AI Interpretation</h4>
            <p>{part1_interps.get('spatial', 'No interpretation available')}</p>
        </div>
    </div>
    """)

    # Part 1-2: Cell Type
    celltype = part1_results.get("celltype", {})
    sections.append(f"""
    <div class="analysis-section">
        <h3>1-2. Cell Type Composition Analysis</h3>
        {generate_figure_html(celltype.get('figure_path'), 'Cell type composition heatmap')}
        <div class="interpretation">
            <h4>AI Interpretation</h4>
            <p>{part1_interps.get('celltype', 'No interpretation available')}</p>
        </div>
    </div>
    """)

    # Part 1-3: Neighborhood
    nhood = part1_results.get("nhood", {})
    sections.append(f"""
    <div class="analysis-section">
        <h3>1-3. Neighborhood Enrichment Analysis</h3>
        {generate_figure_html(nhood.get('figure_path'), 'Neighborhood enrichment matrix')}
        <div class="interpretation">
            <h4>AI Interpretation</h4>
            <p>{part1_interps.get('nhood', 'No interpretation available')}</p>
        </div>
    </div>
    """)

    # Part 1-4: Decoupler
    decoupler = part1_results.get("decoupler", {})
    sections.append(f"""
    <div class="analysis-section">
        <h3>1-4. Spatial Pathway Enrichment (Decoupler)</h3>
        {generate_figure_html(decoupler.get('figure_path'), 'Pathway enrichment analysis')}
        <div class="interpretation">
            <h4>AI Interpretation</h4>
            <p>{part1_interps.get('decoupler', 'No interpretation available')}</p>
        </div>
        <div class="key-findings">
            <h4>Selected Pathways</h4>
            <ul>
                {''.join([f'<li>{pw}</li>' for pw in selected_pathways[:7]]) if selected_pathways else '<li>None selected</li>'}
            </ul>
        </div>
    </div>
    """)

    # Part 1-5: MISTy
    misty = part1_results.get("misty", {})
    sections.append(f"""
    <div class="analysis-section">
        <h3>1-5. Spatial Pathway-CellType Relationship (MISTy)</h3>
        {generate_figure_html(misty.get('figure_path'), 'Pathway-celltype relationship')}
        <div class="interpretation">
            <h4>AI Interpretation</h4>
            <p>{part1_interps.get('misty', 'No interpretation available')}</p>
        </div>
    </div>
    """)

    # Part 1 Synthesis
    if "synthesis" in part1_interps:
        sections.append(f"""
        <div class="summary-box">
            <h3>Part 1 Synthesis</h3>
            <p>{part1_interps['synthesis']}</p>
        </div>
        """)

    return "\n".join(sections)


def generate_part2_content(
    part2_results: dict,
    part2_interps: dict,
    selected_factor: str,
    selected_lr_pairs: list[str],
    state: BiologicalInterpreterState,
) -> str:
    """Generate Part 2 content with figures and interpretations."""
    sections = []

    lr_scores = state.get("lr_scores", {})
    scoring_weights = state.get("scoring_weights", {})

    # Part 2-6: Moran's R
    morans = part2_results.get("morans", {})
    sections.append(f"""
    <div class="analysis-section">
        <h3>2-6. LIANA Moran's R Analysis</h3>
        {generate_figure_html(morans.get('figure_path'), 'Moran R values for L-R pairs')}
        <div class="interpretation">
            <h4>AI Interpretation</h4>
            <p>{part2_interps.get('morans', 'No interpretation available')}</p>
        </div>
    </div>
    """)

    # Part 2-7: NMF Factors
    nmf = part2_results.get("nmf_factors", {})
    sections.append(f"""
    <div class="analysis-section">
        <h3>2-7. NMF Factor Analysis</h3>
        {generate_figure_html(nmf.get('figure_path'), 'NMF factor spatial distribution')}
        <div class="interpretation">
            <h4>AI Interpretation</h4>
            <p>{part2_interps.get('nmf', 'No interpretation available')}</p>
        </div>
        <div class="key-findings">
            <h4>Selected Factor: <span class="score-badge score-high">{selected_factor}</span></h4>
        </div>
    </div>
    """)

    # Part 2-8: Pathway-Factor
    pathway = part2_results.get("pathway_factor", {})
    sections.append(f"""
    <div class="analysis-section">
        <h3>2-8. Pathway-Factor Analysis</h3>
        {generate_figure_html(pathway.get('figure_path'), 'Pathway enrichment by factor')}
        <div class="interpretation">
            <h4>AI Interpretation</h4>
            <p>{part2_interps.get('pathway_factor', 'No interpretation available')}</p>
        </div>
    </div>
    """)

    # Part 2-9: ctSVG
    ctsvg = part2_results.get("ctsvg", {})

    # Generate LR scores table
    lr_table_rows = []
    for lr_name in selected_lr_pairs:
        score = lr_scores.get(lr_name, {})
        lr_table_rows.append(f"""
        <tr>
            <td>{lr_name}</td>
            <td>{score.get('composite_score', 0):.3f}</td>
            <td>{score.get('factor_score', 0):.3f}</td>
            <td>{score.get('pathway_score', 0):.3f}</td>
            <td>{score.get('morans_score', 0):.3f}</td>
            <td>{score.get('ctsvg_score', 0):.3f}</td>
        </tr>
        """)

    weights_info = ""
    if scoring_weights and "applied_weights" in scoring_weights:
        w = scoring_weights["applied_weights"]
        weights_info = f"""
        <p><strong>Applied Weights:</strong> Factor={w.get('factor', 0):.2f},
        Pathway={w.get('pathway', 0):.2f}, Morans={w.get('morans', 0):.2f},
        ctSVG={w.get('ctsvg', 0):.2f}</p>
        <p><em>{scoring_weights.get('adjustment_rationale', '')}</em></p>
        """

    sections.append(f"""
    <div class="analysis-section">
        <h3>2-9. ctSVG Analysis & L-R Selection</h3>
        {generate_figure_html(ctsvg.get('figure_path'), 'Quadrant analysis')}
        <div class="interpretation">
            <h4>AI Interpretation</h4>
            <p>{part2_interps.get('ctsvg', 'No interpretation available')}</p>
        </div>
        {weights_info}
        <h4>Selected L-R Pairs (Composite Scoring)</h4>
        <table>
            <tr>
                <th>L-R Pair</th>
                <th>Composite</th>
                <th>Factor</th>
                <th>Pathway</th>
                <th>Morans</th>
                <th>ctSVG</th>
            </tr>
            {''.join(lr_table_rows) if lr_table_rows else '<tr><td colspan="6">No L-R pairs selected</td></tr>'}
        </table>
    </div>
    """)

    return "\n".join(sections)


def generate_part3_content(
    part2_results: dict,
    part3_interps: dict,
    selected_lr_pairs: list[str],
) -> str:
    """Generate Part 3 content."""
    sections = []

    # Part 3-10: Spatial L-R
    spatial_lr = part2_results.get("spatial_lr", {})
    sections.append(f"""
    <div class="analysis-section">
        <h3>3-10. Spatial L-R Expression Patterns</h3>
        {generate_figure_html(spatial_lr.get('figure_path'), 'Spatial L-R expression')}
        <div class="interpretation">
            <h4>AI Interpretation</h4>
            <p>{part3_interps.get('spatial_lr', 'No interpretation available')}</p>
        </div>
    </div>
    """)

    # Part 3-11: L-R Summary
    lr_summary = part2_results.get("lr_summary", {})
    sections.append(f"""
    <div class="analysis-section">
        <h3>3-11. L-R Interaction Summary</h3>
        {generate_figure_html(lr_summary.get('figure_path'), 'L-R interaction summary')}
        <div class="interpretation">
            <h4>AI Interpretation</h4>
            <p>{part3_interps.get('lr_summary', 'No interpretation available')}</p>
        </div>
        <div class="key-findings">
            <h4>Final Selected L-R Pairs</h4>
            <ul>
                {''.join([f'<li>{lr}</li>' for lr in selected_lr_pairs]) if selected_lr_pairs else '<li>None selected</li>'}
            </ul>
        </div>
    </div>
    """)

    return "\n".join(sections)


def generate_synthesis_content(
    narrative: str,
    reflection_result: dict,
) -> str:
    """Generate synthesis content."""
    # Quality scores
    bio_score = reflection_result.get("biological_plausibility_score", 0)
    evidence_score = reflection_result.get("evidence_coverage_score", 0)
    consistency_score = reflection_result.get("cross_part_consistency_score", 0)

    html = f"""
    <div class="analysis-section">
        <h3>Integrated Biological Narrative</h3>
        <div class="interpretation">
            <p>{narrative}</p>
        </div>
    </div>

    <div class="analysis-section">
        <h3>Quality Assessment</h3>
        <div class="key-findings">
            <h4>Biological Plausibility</h4>
            <div class="confidence-bar">
                <div class="confidence-fill" style="width: {bio_score * 100}%"></div>
            </div>
            <p>{bio_score:.2f}</p>

            <h4>Evidence Coverage</h4>
            <div class="confidence-bar">
                <div class="confidence-fill" style="width: {evidence_score * 100}%"></div>
            </div>
            <p>{evidence_score:.2f}</p>

            <h4>Cross-Part Consistency</h4>
            <div class="confidence-bar">
                <div class="confidence-fill" style="width: {consistency_score * 100}%"></div>
            </div>
            <p>{consistency_score:.2f}</p>
        </div>
    </div>
    """
    return html


def generate_claims_content(
    claims: list,
    literature_evidence: dict,
) -> str:
    """Generate claims content with evidence."""
    sections = []

    for claim in claims:
        claim_id = claim.get("claim_id", "")
        content = claim.get("content", "")
        confidence = claim.get("confidence", 0)
        evidence = claim.get("supporting_evidence", [])
        source = claim.get("part_source", "")
        pmids = literature_evidence.get(claim_id, [])

        confidence_class = "score-high" if confidence >= 0.8 else "score-medium" if confidence >= 0.6 else "score-low"

        pmid_links = ", ".join([
            f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}" class="reference" target="_blank">PMID:{pmid}</a>'
            for pmid in pmids[:3]
        ]) if pmids else "No literature references"

        sections.append(f"""
        <div class="claim-box">
            <div class="claim-content">
                {content}
                <span class="score-badge {confidence_class}">Confidence: {confidence:.2f}</span>
            </div>
            <div class="claim-evidence">
                <p><strong>Source:</strong> {source}</p>
                <p><strong>Evidence:</strong> {', '.join(evidence[:3]) if evidence else 'None'}</p>
                <p><strong>Literature:</strong> {pmid_links}</p>
            </div>
        </div>
        """)

    return f"""
    <div class="analysis-section">
        <h3>Biological Claims with Evidence</h3>
        {''.join(sections) if sections else '<p>No claims generated</p>'}
    </div>
    """


def generate_figure_html(figure_path: str | None, caption: str) -> str:
    """Generate HTML for a figure."""
    if figure_path:
        return f"""
        <div class="figure-container">
            <img src="{figure_path}" alt="{caption}">
            <p class="figure-caption">{caption}</p>
        </div>
        """
    return f"""
    <div class="figure-container">
        <p style="color: #666; padding: 40px;">Figure not available</p>
        <p class="figure-caption">{caption}</p>
    </div>
    """

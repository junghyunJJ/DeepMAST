---
name: html-report-generator
description: Complete HTML report generation workflow for CCI analysis - provides structure, color theme, CSS classes, citation format, and tool usage guidance for publication-quality reports.
---

# HTML Report Generator Skill

Complete workflow for generating publication-quality HTML reports for Spatial Transcriptomics and Cell-Cell Interaction (CCI) analysis interpretations.

## Purpose

This skill provides the **complete workflow** for the REPORTER subagent. It defines:
- **WHAT** to generate (report structure and sections)
- **HOW** to style (color theme and CSS classes)
- **WHERE** to place content (HTML structure and layout)
- **HOW** to cite (citation format and cross-references)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│          This SKILL.md (Workflow Definition)                     │
│  - Report Structure & Sections                                   │
│  - Color Theme & CSS Classes                                     │
│  - Citation Format & Cross-References                            │
│  - Tool Usage & Integration                                      │
└────────────────────────────┬────────────────────────────────────┘
                             │ (REPORTER reads workflow, then calls tools)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│          Python Tools (Execution Layer)                          │
│  - generate_html_report: Main report generation tool             │
│  - generate_simple_report: Simplified wrapper function           │
│  - CSS/JS loaded from assets/ directory                          │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│          Output Files                                            │
│  - Self-contained HTML with embedded CSS/JS                      │
│  - Base64-encoded figures (no external dependencies)             │
│  - Cross-referenced citations with PubMed links                  │
└─────────────────────────────────────────────────────────────────┘
```

## File Structure

```
skills/html-report-generator/
├── SKILL.md                    # This documentation (workflow definition)
├── assets/
│   ├── theme.css               # Full CSS with :root variables
│   └── interactive.js          # Tab navigation and pagination
└── examples/
    └── reference_report.html   # Comprehensive reference with real Visium breast cancer data
```

**Note**: The reference example uses `<link>` to external CSS/JS files for maintainability,
while actual generated reports embed CSS/JS inline for self-contained distribution.
Both approaches are valid; see `report.py` for the inline embedding logic.

---

## Color Theme Reference

### Core Palette

| Color | Hex Code | CSS Variable | Usage |
|-------|----------|--------------|-------|
| **Indigo** | `#818CF8` | `--color-primary` | Titles, links, cell type highlights, borders |
| **Amber** | `#FBBF24` | `--color-secondary` | H3 headings, cluster highlights, pathway boxes |
| **Red** | `#F87171` | `--color-accent` | H4 headings, pathway highlights, key findings |

### Background Colors

| Color | Hex/RGBA | CSS Variable | Usage |
|-------|----------|--------------|-------|
| **Black** | `#000000` | `--bg-primary` | Body background (radial gradient) |
| **Near-Black** | `#0A0A0A` | `--bg-secondary` | Gradient center |
| **Container** | `rgba(17, 17, 17, 0.8)` | `--bg-container` | Glass morphism container + blur |
| **Section** | `rgba(24, 24, 27, 0.6)` | `--bg-section` | Glass morphism sections + blur |
| **Figure** | `rgba(17, 17, 17, 0.5)` | `--bg-figure` | Figure containers |

### Text Colors

| Color | Hex Code | CSS Variable | Usage |
|-------|----------|--------------|-------|
| **Primary** | `#EDEDED` | `--text-primary` | Main body text (off-white) |
| **Secondary** | `#A1A1AA` | `--text-secondary` | Subtitles, captions (zinc-400) |
| **Muted** | `#71717A` | `--text-muted` | Metadata, footer (zinc-500) |

### Semantic Highlight Colors

| Class | Color | Usage Example |
|-------|-------|---------------|
| `.highlight-cluster` | Amber (`#FBBF24`) | `<span class="highlight-cluster">Cluster 5</span>` |
| `.highlight-pathway` | Red (`#F87171`) | `<span class="highlight-pathway">TGFb signaling</span>` |
| `.highlight-celltype` | Indigo (`#818CF8`) | `<span class="highlight-celltype">Macrophages</span>` |

### Light Theme

The report supports a light theme via the `data-theme="light"` HTML attribute, toggled by the theme button.

| Color | Hex Code | CSS Variable | Usage |
|-------|----------|--------------|-------|
| **Indigo-500** | `#6366F1` | `--color-primary` | Titles, links, cell type highlights |
| **Amber-600** | `#D97706` | `--color-secondary` | H3 headings, cluster highlights |
| **Red-600** | `#DC2626` | `--color-accent` | H4 headings, pathway highlights |
| **Off-White** | `#FAFAFA` | `--bg-primary` | Body background |
| **Zinc-100** | `#F4F4F5` | `--bg-secondary` | Secondary background |
| **Zinc-900** | `#18181B` | `--text-primary` | Main body text |

Toggle via JavaScript: `toggleTheme()` switches between `data-theme="dark"` and `data-theme="light"`. Glass morphism (backdrop-blur) is removed in light theme for solid white cards.

---

## HTML Structure Guide

### Report Layout

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <title>{title}</title>
    <style>{css}</style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>
        <p class="subtitle">{subtitle}</p>

        <!-- Executive Summary -->
        <div class="summary-box">...</div>

        <!-- Analysis Configuration -->
        <div class="analysis-section">...</div>

        <!-- Tab Navigation -->
        <div class="tabs">...</div>

        <!-- Tab Contents -->
        <div id="part1" class="tab-content active">...</div>
        <div id="part2" class="tab-content">...</div>
        <div id="part3" class="tab-content">...</div>
        <div id="summary" class="tab-content">...</div>

        <!-- Metadata -->
        <div class="metadata">...</div>
    </div>
    <script>{js}</script>
</body>
</html>
```

### Section Components

#### Container (`.container`)
Main wrapper with max-width, background, and shadow.
```html
<div class="container">
    <!-- All content goes here -->
</div>
```

#### Summary Box (`.summary-box`)
Gradient background box for executive summary.
```html
<div class="summary-box">
    <h3>Executive Summary</h3>
    <p>Summary content with <span class="highlight-pathway">pathway</span> mentions.</p>
</div>
```

#### Analysis Section (`.analysis-section`)
Glass morphism section with indigo left border.
```html
<div class="analysis-section">
    <h3>Section Title</h3>
    <p>Section content...</p>
</div>
```

#### Interpretation Block (`.interpretation`)
Indigo-bordered box for biological interpretations.
```html
<div class="interpretation">
    <h4>Biological Interpretation</h4>
    <p>Our finding of X is consistent with...</p>
</div>
```

#### Key Findings Box (`.key-findings`)
Red-tinted box for important findings lists.
```html
<div class="key-findings">
    <h4>Key Findings</h4>
    <ul>
        <li>Finding 1</li>
        <li>Finding 2</li>
    </ul>
</div>
```

#### Pathway Box (`.pathway-box`)
Amber-bordered box for pathway descriptions.
```html
<div class="pathway-box">
    <h4>Top Enriched Pathways</h4>
    <ul>
        <li><span class="highlight-pathway">TGFb signaling</span> (Activity: 2.3)</li>
        <li><span class="highlight-pathway">Hypoxia response</span> (Activity: 1.8)</li>
    </ul>
</div>
```

#### Figure Container (`.figure-container`)
Centered container for embedded figures.
```html
<div class="figure-container">
    <img src="data:image/png;base64,..." alt="Figure description">
    <p class="figure-caption">Figure 1.1: Spatial distribution of clusters.</p>
</div>
```

### Tab Navigation

#### Tab Buttons (`.tabs`, `.tab-button`)
```html
<div class="tabs">
    <button class="tab-button active" onclick="openTab(event, 'part1')">Part 1</button>
    <button class="tab-button" onclick="openTab(event, 'part2')">Part 2</button>
    <button class="tab-button" onclick="openTab(event, 'part3')">Part 3</button>
    <button class="tab-button" onclick="openTab(event, 'summary')">Summary</button>
</div>
```

#### Tab Content (`.tab-content`)
```html
<div id="part1" class="tab-content active">
    <!-- Part 1 content (visible by default) -->
</div>
<div id="part2" class="tab-content">
    <!-- Part 2 content (hidden until clicked) -->
</div>
```

### Pagination for L-R Tables

#### Pagination Controls (`.pagination`, `.page-button`)
```html
<div class="pagination">
    <button class="page-button active" onclick="showPage(1)">1</button>
    <button class="page-button" onclick="showPage(2)">2</button>
    <button class="page-button" onclick="showPage(3)">3</button>
</div>
```

#### Paginated Content (`.interactions-page`)
```html
<div id="interactions-page-1" class="interactions-page active">
    <!-- Page 1 content (visible by default) -->
</div>
<div id="interactions-page-2" class="interactions-page">
    <!-- Page 2 content (hidden until page button clicked) -->
</div>
```

### Table Components

```html
<div class="table-container">
    <table>
        <tr>
            <th>Ligand</th>
            <th>Receptor</th>
            <th>Moran's R</th>
        </tr>
        <tr>
            <td>TGFB1</td>
            <td>TGFBR2</td>
            <td>0.45</td>
        </tr>
    </table>
</div>
```

### Score Badges

```html
<span class="score-badge score-high">0.85</span>   <!-- Green/Cyan for >= 0.7 -->
<span class="score-badge score-medium">0.55</span> <!-- Yellow for 0.5-0.7 -->
<span class="score-badge score-low">0.35</span>    <!-- Pink for < 0.5 -->
```

### Confidence Bar

```html
<div class="confidence-bar">
    <div class="confidence-fill" style="width: 85%"></div>
</div>
```

### Reference Components

#### Paper Card (`.paper-card`)
```html
<div class="paper-card">
    <div class="paper-title">
        <a href="https://pubmed.ncbi.nlm.nih.gov/12345678/" target="_blank">
            Author et al. (2023) - Paper title here
        </a>
    </div>
</div>
```

#### Inline Reference Link (`.reference`)
```html
<a href="https://pubmed.ncbi.nlm.nih.gov/12345678/" class="reference" target="_blank">
    PMID: 12345678
</a>
```

---

## Tool Reference

**Note**: The REPORTER agent also has access to `read_file` and `write_file` functions
provided by the DeepAgents FilesystemBackend middleware. These are not listed in the
explicit tool configuration but are always available for reading/writing virtual filesystem files.

### generate_html_report()

Main tool for generating comprehensive HTML reports.

**Parameters:**
```python
generate_html_report(
    parts: dict,       # Report content dictionary
    output_path: str   # Output file path (e.g., "res/report.html")
)
```

**`parts` Dictionary Structure:**
```python
parts = {
    # Required fields
    "title": "CCI Analysis Report",
    "subtitle": "Comprehensive Analysis of Sample X",
    "executive_summary": "<p>Summary with <span class='highlight-pathway'>highlights</span></p>",
    "analysis_config": "<table>...</table>",

    # Structured mode (default)
    "part1": {
        "Analysis Name": {
            "figure_path": "res/figure1.png",      # Path to figure (embedded as Base64)
            "interpretation": "Interpretation text...",
            "caption": "Figure caption",
            "references": [{"pmid": "12345678", "title": "Paper title"}]
        }
    },
    "part2": {...},
    "part3": {...},

    "synthesis": "Integrated biological narrative...",
    "quality_score": 0.85,  # 0.0 to 1.0
    "references": [{"pmid": "12345678", "title": "Paper title"}],

    # OR: HTML override mode (for LLM-generated HTML)
    "part1_html": "<h2>Part 1</h2><div class='analysis-section'>...</div>",
    "part2_html": "...",
    "part3_html": "...",
    "summary_html": "..."
}
```

**Returns:**
```
"Report generated successfully: res/report.html (125432 bytes)"
```

### Structured Mode vs HTML Override Mode

| Mode | When to Use | Input Format |
|------|-------------|--------------|
| **Structured** | Consistent formatting, automatic figure embedding | `part1`, `part2`, `part3` dicts |
| **HTML Override** | Custom layouts, complex formatting | `part1_html`, `part2_html`, `part3_html` strings |

**Structured Mode Example:**
```python
generate_html_report(
    parts={
        "title": "Report",
        "subtitle": "Analysis",
        "executive_summary": "Summary text",
        "analysis_config": "",
        "part1": {
            "Spatial Analysis": {
                "figure_path": "res/spatial.png",
                "interpretation": "The spatial distribution shows...",
                "caption": "Spatial clustering",
                "references": []
            }
        },
        "part2": {},
        "part3": {},
        "synthesis": "Overall findings...",
        "quality_score": 0.8,
        "references": []
    },
    output_path="res/report.html"
)
```

**HTML Override Mode Example:**
```python
generate_html_report(
    parts={
        "title": "CCI Analysis Report",
        "subtitle": "Comprehensive Cell-Cell Interaction Analysis",
        "executive_summary": "<p>Overview paragraph.</p><div class='key-findings'><h4>Key Findings:</h4><ul><li><strong>Finding 1:</strong> Detail with <span class='highlight-pathway'>pathway</span></li><li><strong>Finding 2:</strong> Detail with <span class='highlight-celltype'>celltype</span></li></ul></div>",
        "analysis_config": {"Target Clusters": "4, 17, 14", "NMF Factor": "Factor3"},
        "part1_html": """
        <div class="analysis-section">
            <h3>1. Spatial Clustering Analysis</h3>
            <div class="figure-container">
                <img src="1.spatial.png" alt="Spatial Clustering">
                <p class="figure-caption">Figure 1: Spatial distribution of tissue clusters.</p>
            </div>
            <div class="key-findings">
                <h4>Key Cellular Compositions:</h4>
                <table>
                    <tr><th>Cluster</th><th>Cell Type</th><th>FDR</th></tr>
                    <tr>
                        <td rowspan="2"><strong class="highlight-cluster">Cluster 4</strong></td>
                        <td class="highlight-celltype">Invasive Tumor</td>
                        <td>2.47 × 10<sup>-244</sup></td>
                    </tr>
                    <tr>
                        <td class="highlight-celltype">Prolif Invasive Tumor</td>
                        <td>7.74 × 10<sup>-237</sup></td>
                    </tr>
                </table>
            </div>
            <div class="interpretation">
                <h4>Biological Interpretation:</h4>
                <p><strong>Invasive Regions:</strong> Cluster 4 shows the strongest enrichment
                of <span class="highlight-celltype">Invasive Tumor</span> cells
                <a href="https://pubmed.ncbi.nlm.nih.gov/39703753/" class="reference" target="_blank">(PMID: 39703753)</a>.</p>
            </div>
        </div>
        <div class="summary-box">
            <h4>Part 1 Summary</h4>
            <ul style="margin-left: 40px;"><li><span class="highlight-pathway">MAPK</span> - Extreme hyperactivation</li></ul>
        </div>
        """,
        "part2_html": "...",
        "part3_html": "...",
        "summary_html": "...",
        "synthesis": "",
        "quality_score": 0.85,
        "references": []
    },
    output_path="res/report.html"
)
```

---

## CSS Class Reference (LLM Quick Reference)

### Layout Classes
| Class | Purpose |
|-------|---------|
| `.container` | Main content wrapper |
| `.summary-box` | Executive summary with gradient |
| `.analysis-section` | Glass morphism section with indigo border |
| `.interpretation` | Interpretation block with indigo border |
| `.key-findings` | Key findings with red tint background |
| `.pathway-box` | Pathway list with amber border |
| `.figure-container` | Centered figure wrapper |
| `.figure-caption` | Figure caption (italic, muted) |

### Navigation Classes
| Class | Purpose |
|-------|---------|
| `.tabs` | Tab button container |
| `.tab-button` | Individual tab button |
| `.tab-button.active` | Active tab (filled background) |
| `.tab-content` | Tab content panel |
| `.tab-content.active` | Visible tab content |
| `.pagination` | Page button container |
| `.page-button` | Individual page button |
| `.interactions-page` | Paginated content panel |

### Table Classes
| Class | Purpose |
|-------|---------|
| `.table-container` | Scrollable table wrapper |
| `table` | Standard table styling |
| `th` | Table header (indigo tint background) |
| `td` | Table cell |

### Highlight Classes
| Class | Color | Purpose |
|-------|-------|---------|
| `.highlight-cluster` | Amber | Cluster names |
| `.highlight-pathway` | Red | Pathway names |
| `.highlight-celltype` | Indigo | Cell type names |

### Score Classes
| Class | Color | Condition |
|-------|-------|-----------|
| `.score-badge.score-high` | Indigo | score >= 0.7 |
| `.score-badge.score-medium` | Amber | 0.5 <= score < 0.7 |
| `.score-badge.score-low` | Red | score < 0.5 |

### Reference Classes
| Class | Purpose |
|-------|---------|
| `.reference` | Inline PubMed link |
| `.paper-card` | Reference card with border |
| `.paper-title` | Paper title container |

---

## Reference-Quality HTML Examples

These examples are extracted from reference reports and demonstrate the target quality for LLM-generated HTML override content.

### Cell Type Composition Table

Complete `key-findings` table with rowspan grouping, FDR columns with `<sup>`, and semantic highlights:

```html
<div class="key-findings">
    <h4>Key Cellular Compositions in Invasive Tumor Regions:</h4>
    <table>
        <tr>
            <th>Cluster</th>
            <th>Cell Type</th>
            <th>Median Composition</th>
            <th>FDR (Adjusted P-value)</th>
            <th>Biological Significance</th>
        </tr>
        <tr>
            <td rowspan="4"><strong class="highlight-cluster">Cluster 4</strong></td>
            <td class="highlight-celltype">Prolif Invasive Tumor</td>
            <td>0.184</td>
            <td>2.47 × 10<sup>-244</sup></td>
            <td>Primary proliferative invasive region</td>
        </tr>
        <tr>
            <td class="highlight-celltype">Invasive Tumor</td>
            <td>0.132</td>
            <td>7.74 × 10<sup>-237</sup></td>
            <td>Core invasive tumor mass</td>
        </tr>
        <tr>
            <td class="highlight-celltype">Perivascular-Like</td>
            <td>0.072</td>
            <td>6.38 × 10<sup>-195</sup></td>
            <td>Vascular support cells</td>
        </tr>
        <tr>
            <td class="highlight-celltype">T Cell &amp; Tumor Hybrid</td>
            <td>0.071</td>
            <td>6.63 × 10<sup>-236</sup></td>
            <td>Immune-tumor interaction zone</td>
        </tr>
        <tr>
            <td rowspan="3"><strong class="highlight-cluster">Cluster 17</strong></td>
            <td class="highlight-celltype">Prolif Invasive Tumor</td>
            <td>0.200</td>
            <td>3.21 × 10<sup>-22</sup></td>
            <td>Highest proliferation rate</td>
        </tr>
        <!-- Additional rows follow same pattern -->
    </table>
</div>
```

### Interpretation Block with Citations

Complete `interpretation` div with bold sub-headings, statistics, and inline PubMed links:

```html
<div class="interpretation">
    <h4>Biological Interpretation:</h4>

    <p><strong>MAPK Pathway Hyperactivation:</strong> The MAPK pathway shows extreme hyperactivation
    across all invasive tumor clusters, with <span class="highlight-cluster">Cluster 4</span>
    displaying the most dramatic activation (stat=47.86, FDR=6.19×10<sup>-204</sup>). The MAPK/ERK
    pathway is a critical driver of breast cancer cell invasion and proliferation
    <a href="https://pubmed.ncbi.nlm.nih.gov/40390063/" class="reference" target="_blank">(PMID: 40390063)</a>.</p>

    <p><strong>PI3K/AKT Signaling:</strong> The <span class="highlight-pathway">PI3K</span> pathway
    shows consistent strong activation across invasive clusters
    (<span class="highlight-cluster">Cluster 4</span>: stat=33.05). The co-activation of both
    <span class="highlight-pathway">MAPK</span> and <span class="highlight-pathway">PI3K</span>
    pathways suggests convergent oncogenic signaling
    <a href="https://pubmed.ncbi.nlm.nih.gov/39382177/" class="reference" target="_blank">(PMID: 39382177)</a>.</p>
</div>
```

### Part Summary Box

Complete `summary-box` at end of each Part tab:

```html
<div class="summary-box">
    <h4>Part 1 Summary: Integrated Findings</h4>
    <p><strong>Selected Tumor Regions:</strong> Clusters 4, 17, and 14 represent the primary
    invasive tumor mass with distinct molecular and spatial characteristics.</p>
    <p><strong>Dominant Pathways:</strong></p>
    <ul style="margin-left: 40px; margin-top: 10px;">
        <li><span class="highlight-pathway">MAPK</span> - Extreme hyperactivation driving proliferation</li>
        <li><span class="highlight-pathway">PI3K</span> - Strong activation supporting survival</li>
        <li><span class="highlight-pathway">Hypoxia</span> - Critical driver of proliferative phenotype</li>
    </ul>
    <p style="margin-top: 10px;"><strong>Key Insight:</strong> Invasive tumor clusters show
    preferential co-localization and strong associations with supportive microenvironmental regions.</p>
</div>
```

### Per-Analysis Structure Pattern

The canonical structure for each analysis section within a Part tab:

```html
<div class="analysis-section">
    <h3>N. Analysis Name</h3>

    <!-- Figure -->
    <div class="figure-container">
        <img src="data:image/png;base64,..." alt="Description">
        <p class="figure-caption">Figure N: Caption describing the visualization.</p>
    </div>

    <!-- Optional: Pathway descriptions -->
    <div class="pathway-box">
        <h4>PROGENy Pathway Descriptions:</h4>
        <ul>
            <li><strong>MAPK:</strong> Integrates external signals and promotes cell growth</li>
            <li><strong>PI3K:</strong> Promotes growth and proliferation</li>
        </ul>
    </div>

    <!-- Optional: Key findings data table -->
    <div class="key-findings">
        <h4>Key Findings Title:</h4>
        <table>
            <!-- Table with rowspan, FDR formatting, semantic highlights -->
        </table>
    </div>

    <!-- Interpretation with inline citations -->
    <div class="interpretation">
        <h4>Biological Interpretation:</h4>
        <p><strong>Sub-heading:</strong> Interpretation text with
        <span class="highlight-pathway">pathway</span> highlights,
        statistics (stat=47.86, FDR=6.19×10<sup>-204</sup>), and
        <a href="https://pubmed.ncbi.nlm.nih.gov/12345678/" class="reference" target="_blank">(PMID: 12345678)</a>.</p>
    </div>
</div>
```

### L-R Pagination Pattern

Complete example of paginated L-R interaction tables for Part 3 (5 rows per page):

```html
<div class="key-findings">
    <h4>Top Prioritized Ligand-Receptor Interactions:</h4>
    <div style="margin: 20px 0;">
        <p><strong>Pagination:</strong> Showing interactions 1-5 of 19 total</p>
        <div class="pagination">
            <button class="page-button active" onclick="showPage(1)">1-5</button>
            <button class="page-button" onclick="showPage(2)">6-10</button>
            <button class="page-button" onclick="showPage(3)">11-15</button>
            <button class="page-button" onclick="showPage(4)">16-19</button>
        </div>
    </div>

    <div id="interactions-page-1" class="interactions-page active">
        <table>
            <tr>
                <th>Rank</th>
                <th>Interaction</th>
                <th>Moran's R</th>
                <th>Factor Loading</th>
                <th>Pathways</th>
                <th>Ligand ctSVG</th>
                <th>Receptor ctSVG</th>
            </tr>
            <tr style="background: rgba(129, 140, 248, 0.06);">
                <td><strong>1</strong></td>
                <td><strong>CDH1^ERBB3</strong></td>
                <td><strong>0.477</strong></td>
                <td><strong>1.197</strong></td>
                <td><span class="highlight-pathway">MAPK, PI3K</span></td>
                <td><span class="highlight-celltype">Invasive Tumor</span>, Myoepi</td>
                <td>Endothelial, <span class="highlight-celltype">Invasive Tumor</span></td>
            </tr>
            <!-- 4 more rows -->
        </table>
    </div>

    <div id="interactions-page-2" class="interactions-page">
        <table>
            <!-- Same header, rows 6-10 -->
        </table>
    </div>
</div>
```

**Key rules for pagination:**
- Use `id="interactions-page-N"` and `class="interactions-page"` (first page also gets `active`)
- Use `onclick="showPage(N)"` on page buttons (first button also gets `active` class)
- 5 rows per page maximum
- Each page has its own complete `<table>` with headers
- Highlight top-ranked row with `style="background: rgba(129, 140, 248, 0.06);"`

### Executive Summary Pattern

Structure for the executive summary `summary-box`:

```html
<div class="summary-box">
    <h3>Executive Summary</h3>
    <p>Overview paragraph describing the analysis scope and key methodology.</p>

    <div class="key-findings">
        <h4>Key Findings:</h4>
        <ul>
            <li><strong>Primary Tumor Clusters:</strong> Clusters show enrichment of
                <span class="highlight-celltype">Invasive Tumor</span> with significance
                (FDR &lt; 10<sup>-20</sup>)</li>
            <li><strong>Dominant Pathway:</strong> <span class="highlight-pathway">MAPK</span>
                shows extreme hyperactivation (stat=47.86)</li>
            <li><strong>Hypoxia-Proliferation Axis:</strong> Strong
                <span class="highlight-pathway">hypoxia</span> signature (MISTy importance=0.764)</li>
            <li><strong>CCI Pattern:</strong> Identified dominant communication pattern enriched
                in all invasive regions</li>
            <li><strong>Critical L-R Interactions:</strong> N significant pairs identified, with
                <strong>CDH1^ERBB3</strong> showing highest significance</li>
            <li><strong>Microenvironment:</strong> Perivascular-Like cells and immune populations
                co-localize with invasive tumor regions</li>
        </ul>
    </div>
</div>
```

**Rules:** 6-8 bullet points, each with `<strong>Category:</strong>` prefix, semantic highlights on key entities, quantitative metrics inline.

### Summary Tab Pattern

Structure for the Comprehensive Summary tab:

```html
<!-- Overall Biological Model -->
<div class="summary-box">
    <h3>Overall Biological Model</h3>
    <p>Integrative paragraph describing the overall model emerging from all analyses.</p>
</div>

<!-- Integrated Findings -->
<div class="analysis-section">
    <h3>Integrated Findings Across All Analyses</h3>

    <h4>1. Spatial Architecture</h4>
    <p>Description with cross-part evidence and
    <a href="..." class="reference" target="_blank">(PMID: ...)</a>.</p>

    <h4>2. Convergent Oncogenic Signaling</h4>
    <p><strong>MAPK Dominance:</strong> Description with quantitative evidence.</p>
    <p><strong>PI3K Co-activation:</strong> Description.</p>

    <h4>3. Intercellular Communication Networks</h4>
    <p>Description linking Part 2 and Part 3 findings.</p>
</div>

<!-- Clinical Implications -->
<div class="analysis-section">
    <h3>Clinical and Therapeutic Implications</h3>
    <h4>Pathway-Based Therapeutic Opportunities</h4>
    <ul style="margin-left: 40px;">
        <li><strong>Target 1:</strong> Rationale with evidence.</li>
        <li><strong>Target 2:</strong> Rationale with evidence.</li>
    </ul>
</div>

<!-- Conclusions -->
<div class="summary-box">
    <h3>Conclusions</h3>
    <p>Concluding paragraph.</p>
    <p><strong>Key Targetable Vulnerabilities Identified:</strong></p>
    <ul style="margin-left: 40px; margin-top: 10px;">
        <li>Vulnerability 1 (highest priority)</li>
        <li>Vulnerability 2</li>
        <li>Vulnerability 3</li>
    </ul>
</div>

<!-- References -->
<div class="analysis-section">
    <h3>References</h3>
    <ul style="margin-left: 20px; line-height: 2;">
        <li><a href="https://pubmed.ncbi.nlm.nih.gov/12345678/" class="reference" target="_blank">PMID: 12345678</a> - Paper title and relevance</li>
    </ul>
</div>
```

**Rules:** Biological Model (summary-box) → Integrated Findings (analysis-section with numbered H4s) → Clinical Implications (analysis-section with ul) → Conclusions (summary-box with vulnerabilities list) → References (analysis-section with linked list).

---

## Citation Format

### In-text Citation
```
(Author et al., Year; PMID: 12345678)
```

**Example:**
> "consistent with previous reports demonstrating that the TREM2-APOE pathway drives microglial phenotype (Krasemann et al., 2017; PMID: 28930663)"

### References Section
```html
<div class="paper-card">
    <div class="paper-title">
        <a href="https://pubmed.ncbi.nlm.nih.gov/28930663/" target="_blank">
            Krasemann et al. (2017) - The TREM2-APOE Pathway Drives the Transcriptional Phenotype of Dysfunctional Microglia
        </a>
    </div>
</div>
```

### Cross-Reference Rules

| Rule | Description |
|------|-------------|
| **Every in-text PMID** | Must appear in References section |
| **Every Reference** | Must be cited at least once in body |
| **No orphan citations** | Citations in body must have matching Reference |
| **Consistent format** | Use `(Author et al., Year; PMID: XXXXXXXX)` |

---

## Report Generation Workflow

### Step-by-Step Process

```
┌─────────────────────────────────────────────────────────────────┐
│  Step 1: Gather Interpretations                                  │
│  - Read Part 1 interpretation from /part1_final.md              │
│  - Read Part 2 interpretation from /part2_final.md              │
│  - Read Part 3 interpretation from /part3_final.md              │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 2: Collect References                                      │
│  - Gather all PMIDs from interpretations                        │
│  - Load paper details from /papers.json                         │
│  - Deduplicate references                                        │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 3: Collect Figures                                         │
│  - Map figure paths for each analysis                            │
│  - Verify figure files exist                                     │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 4: Generate Report                                         │
│  - Call generate_html_report() with parts dict                   │
│  - Figures embedded as Base64 (self-contained)                   │
│  - CSS/JS loaded from assets/ (or fallback)                      │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 5: Verify Output                                           │
│  - Check file size and creation                                  │
│  - Validate all citations have references                        │
│  - Open in browser for visual verification                       │
└─────────────────────────────────────────────────────────────────┘
```

### Virtual Filesystem Integration

| File | Purpose |
|------|---------|
| `/data_path.txt` | Real data directory path |
| `/part1_final.md` | Part 1 interpretation text |
| `/part2_final.md` | Part 2 interpretation text |
| `/part3_final.md` | Part 3 interpretation text |
| `/papers.json` | Literature references (all parts) |

---

## Integration with Other Skills

### biomedical-literature-search Integration

```
biomedical-literature-search
        │
        │ search_literature_dynamic() / search_literature()
        ▼
    papers: [{pmid, title, authors}]
        │
        │ Write Part interpretation with citations
        ▼
    /partN_final.md
        │
        │ (After all parts complete)
        ▼
html-report-generator
        │
        │ generate_html_report(parts, references)
        ▼
    report.html (self-contained)
```

### Data Transformation

**From search results:**
```python
{
    "papers": [
        {"pmid": "28930663", "title": "The TREM2-APOE...", "authors": "Krasemann S", "year": "2017"}
    ]
}
```

**To generate_html_report:**
```python
{
    "references": [
        {"pmid": "28930663", "title": "The TREM2-APOE Pathway...", "authors": "Krasemann S", "year": "2017"}
    ]
}
```

---

## Common Mistakes to Avoid

### FORBIDDEN ACTIONS

- **DO NOT** forget to include figure paths - reports will show "Figure not available"
- **DO NOT** use relative paths for figures - always use paths from data directory
- **DO NOT** mix citation formats - use consistent `(Author et al., Year; PMID: XXXXXXXX)`
- **DO NOT** leave orphan citations - every in-text PMID needs a Reference entry
- **DO NOT** use HTML entities in plain text fields - they won't render correctly
- **DO NOT** include raw DataFrames in state - use file paths for serialization

### CORRECT ACTIONS

- **DO** embed figures using the `figure_path` field - tool handles Base64 encoding
- **DO** use semantic highlight classes - `.highlight-cluster`, `.highlight-pathway`, `.highlight-celltype`
- **DO** use the appropriate mode - Structured for consistency, HTML Override for custom layouts
- **DO** verify citation cross-references before generating final report
- **DO** check the reference example at `examples/reference_report.html` for structure
- **DO** customize colors via CSS variables in `assets/theme.css` if needed

---

## Quick Reference Card

### Color Codes

| Element | Color | Hex |
|---------|-------|-----|
| Titles/Links | Indigo | `#818CF8` |
| H3/Clusters | Amber | `#FBBF24` |
| H4/Pathways | Red | `#F87171` |
| Body Text | Off-White | `#EDEDED` |
| Background | Black | `#000000` |

### CSS Class Cheatsheet

```html
<!-- Sections -->
<div class="summary-box">Executive Summary</div>
<div class="analysis-section">Analysis Section</div>
<div class="interpretation">Interpretation</div>
<div class="key-findings">Key Findings</div>
<div class="pathway-box">Pathway List</div>

<!-- Highlights -->
<span class="highlight-cluster">Cluster 5</span>
<span class="highlight-pathway">TGFb signaling</span>
<span class="highlight-celltype">Macrophages</span>

<!-- Scores -->
<span class="score-badge score-high">0.85</span>

<!-- Figures -->
<div class="figure-container">
    <img src="..." alt="...">
    <p class="figure-caption">Caption</p>
</div>

<!-- Tabs -->
<button class="tab-button active" onclick="openTab(event, 'id')">Label</button>
<div id="id" class="tab-content active">Content</div>

<!-- Pagination -->
<button class="page-button" onclick="showPage(1)">1</button>
<div id="interactions-page-1" class="interactions-page">Content</div>
```

### JavaScript Functions

| Function | Purpose | Usage |
|----------|---------|-------|
| `openTab(event, tabId)` | Switch tabs | `onclick="openTab(event, 'part1')"` |
| `showPage(pageNum)` | Switch pages | `onclick="showPage(1)"` |
| `toggleTheme()` | Toggle dark/light theme | `onclick="toggleTheme()"` |

### Tool Quick Reference

```python
# Structured mode
generate_html_report(
    parts={
        "title": "...", "subtitle": "...",
        "executive_summary": "...", "analysis_config": "...",
        "part1": {"Analysis": {"figure_path": "...", "interpretation": "..."}},
        "part2": {...}, "part3": {...},
        "synthesis": "...", "quality_score": 0.85,
        "references": [{"pmid": "...", "title": "..."}]
    },
    output_path="res/report.html"
)

# HTML override mode
generate_html_report(
    parts={
        "title": "...", "subtitle": "...",
        "executive_summary": "...", "analysis_config": "...",
        "part1_html": "<h2>...</h2>...",
        "part2_html": "...", "part3_html": "...", "summary_html": "...",
        "synthesis": "", "quality_score": 0.85, "references": []
    },
    output_path="res/report.html"
)
```

---

## Example Workflow

### Input Context
> REPORTER receives interpretations for Part 1, 2, 3 and needs to generate final HTML report.

### Step 1: Read Interpretations
```python
part1_text = read_file("/part1_final.md")
part2_text = read_file("/part2_final.md")
part3_text = read_file("/part3_final.md")
```

### Step 2: Collect References
```python
papers = json.loads(read_file("/papers.json"))

all_references = []
for paper in papers["papers"]:
    all_references.append({"pmid": paper["pmid"], "title": paper["title"]})
```

### Step 3: Build Parts Dictionary
```python
parts = {
    "title": "Breast Cancer CCI Analysis Report",
    "subtitle": "Comprehensive Spatial Transcriptomics Analysis",
    "executive_summary": "<p>Analysis reveals <span class='highlight-pathway'>TGFb signaling</span>...</p>",
    "analysis_config": "<table>...</table>",
    "part1_html": format_part1_html(part1_text),
    "part2_html": format_part2_html(part2_text),
    "part3_html": format_part3_html(part3_text),
    "summary_html": format_summary_html(synthesis_text),
    "synthesis": "",
    "quality_score": 0.85,
    "references": all_references
}
```

### Step 4: Generate Report
```python
result = generate_html_report(
    parts=parts,
    output_path="res/Breast_Cancer_CCI_Analysis_Report.html"
)
# Returns: "Report generated successfully: res/Breast_Cancer_CCI_Analysis_Report.html (156789 bytes)"
```

### Step 5: Verify
- Open report in browser
- Check all tabs work
- Verify figures are embedded
- Confirm citations match references

---

## Customization Guide

### Modifying Colors

Edit `skills/html-report-generator/assets/theme.css`:

```css
:root {
    /* Default: Indigo primary */
    --color-primary: #818CF8;

    /* Default: Amber secondary */
    --color-secondary: #FBBF24;

    /* Default: Red accent */
    --color-accent: #F87171;
}
```

### Adding New CSS Classes

Add to `assets/theme.css`:

```css
/* Custom class for gene highlights */
.highlight-gene {
    color: #9d65ff;  /* Purple */
    font-weight: bold;
    font-family: monospace;
}
```

### Modifying JavaScript

Edit `skills/html-report-generator/assets/interactive.js` to add new functionality.

---

## Troubleshooting

### Report shows "Figure not available"
- Verify figure file exists at the specified path
- Check path is correct (relative to working directory)
- Ensure file has readable permissions

### CSS not loading correctly
- Check `skills/html-report-generator/assets/theme.css` exists
- Fallback CSS is used if file not found
- Check for syntax errors in CSS file

### Citations don't match references
- Cross-check all in-text PMIDs with References section
- Use biomedical-literature-search to ensure papers are retrieved
- Verify JSON structure of papers files

### Tabs not working
- Check JavaScript loaded correctly
- Verify `id` attributes match `onclick` parameters
- Ensure `tab-content` classes are correct

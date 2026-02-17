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
| **Cyan** | `#64ffda` | `--color-primary` | Titles, links, cell type highlights, borders |
| **Yellow** | `#ffd166` | `--color-secondary` | H3 headings, cluster highlights, pathway boxes |
| **Pink** | `#ff6b9d` | `--color-accent` | H4 headings, pathway highlights, key findings |

### Background Colors

| Color | Hex/RGBA | CSS Variable | Usage |
|-------|----------|--------------|-------|
| **Dark Blue** | `#1a1a2e` | `--bg-primary` | Body background (gradient start) |
| **Darker Blue** | `#16213e` | `--bg-secondary` | Body background (gradient end) |
| **Container** | `rgba(26, 26, 46, 0.95)` | `--bg-container` | Main container |
| **Section** | `rgba(35, 35, 60, 0.6)` | `--bg-section` | Analysis sections |
| **Figure** | `rgba(0, 0, 0, 0.3)` | `--bg-figure` | Figure containers |

### Text Colors

| Color | Hex Code | CSS Variable | Usage |
|-------|----------|--------------|-------|
| **Primary** | `#e4e4e4` | `--text-primary` | Main body text |
| **Secondary** | `#aaa` | `--text-secondary` | Subtitles, captions |
| **Muted** | `#666` | `--text-muted` | Metadata, footer |

### Semantic Highlight Colors

| Class | Color | Usage Example |
|-------|-------|---------------|
| `.highlight-cluster` | Yellow (`#ffd166`) | `<span class="highlight-cluster">Cluster 5</span>` |
| `.highlight-pathway` | Pink (`#ff6b9d`) | `<span class="highlight-pathway">TGFb signaling</span>` |
| `.highlight-celltype` | Cyan (`#64ffda`) | `<span class="highlight-celltype">Macrophages</span>` |

### Light Theme

The report supports a light theme via the `data-theme="light"` HTML attribute, toggled by the theme button.

| Color | Hex Code | CSS Variable | Usage |
|-------|----------|--------------|-------|
| **Blue** | `#0066cc` | `--color-primary` | Titles, links, cell type highlights |
| **Dark Gold** | `#b8860b` | `--color-secondary` | H3 headings, cluster highlights |
| **Dark Pink** | `#cc3366` | `--color-accent` | H4 headings, pathway highlights |
| **Light Gray** | `#f8f9fa` | `--bg-primary` | Body background |
| **White** | `#ffffff` | `--bg-secondary` | Secondary background |
| **Dark Text** | `#2c3e50` | `--text-primary` | Main body text |

Toggle via JavaScript: `toggleTheme()` switches between `data-theme="dark"` and `data-theme="light"`.

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
Standard section with cyan left border.
```html
<div class="analysis-section">
    <h3>Section Title</h3>
    <p>Section content...</p>
</div>
```

#### Interpretation Block (`.interpretation`)
Cyan-bordered box for biological interpretations.
```html
<div class="interpretation">
    <h4>Biological Interpretation</h4>
    <p>Our finding of X is consistent with...</p>
</div>
```

#### Key Findings Box (`.key-findings`)
Pink-tinted box for important findings lists.
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
Yellow-bordered box for pathway descriptions.
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
        "title": "Report",
        "subtitle": "Analysis",
        "executive_summary": "Summary",
        "analysis_config": "",
        "part1_html": """
        <h2>Part 1: Spatial Analysis</h2>
        <div class="analysis-section">
            <h3>1.1 Spatial Distribution</h3>
            <div class="figure-container">
                <img src="data:image/png;base64,..." alt="Spatial plot">
                <p class="figure-caption">Figure 1.1: Spatial clusters</p>
            </div>
            <div class="interpretation">
                <h4>Biological Interpretation</h4>
                <p>Our analysis reveals...</p>
            </div>
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
| `.analysis-section` | Standard section with cyan border |
| `.interpretation` | Interpretation block with cyan border |
| `.key-findings` | Key findings with pink background |
| `.pathway-box` | Pathway list with yellow border |
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
| `th` | Table header (cyan background) |
| `td` | Table cell |

### Highlight Classes
| Class | Color | Purpose |
|-------|-------|---------|
| `.highlight-cluster` | Yellow | Cluster names |
| `.highlight-pathway` | Pink | Pathway names |
| `.highlight-celltype` | Cyan | Cell type names |

### Score Classes
| Class | Color | Condition |
|-------|-------|-----------|
| `.score-badge.score-high` | Cyan | score >= 0.7 |
| `.score-badge.score-medium` | Yellow | 0.5 <= score < 0.7 |
| `.score-badge.score-low` | Pink | score < 0.5 |

### Reference Classes
| Class | Purpose |
|-------|---------|
| `.reference` | Inline PubMed link |
| `.paper-card` | Reference card with border |
| `.paper-title` | Paper title container |

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
│  - Load paper details from /part1_papers.json, /liana_papers.json│
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
| `/part1_papers.json` | Part 1 literature references |
| `/liana_papers.json` | Part 2+3 literature references |

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
| Titles/Links | Cyan | `#64ffda` |
| H3/Clusters | Yellow | `#ffd166` |
| H4/Pathways | Pink | `#ff6b9d` |
| Body Text | Light Gray | `#e4e4e4` |
| Background | Dark Blue | `#1a1a2e` |

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
part1_papers = json.loads(read_file("/part1_papers.json"))
liana_papers = json.loads(read_file("/liana_papers.json"))

all_references = []
for paper in part1_papers["papers"] + liana_papers["papers"]:
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
    /* Change primary color from cyan to blue */
    --color-primary: #4a90d9;

    /* Change secondary color from yellow to orange */
    --color-secondary: #ff9f43;

    /* Keep accent pink or change as needed */
    --color-accent: #ff6b9d;
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

---
name: html-report-generator
description: Citation formatting and cross-reference rules for CCI analysis HTML reports. Integrates with biomedical-literature-search for literature citations.
---

# HTML Report Citation Guide

## HTML Format Reference
See example report for structure and styling:
`res/Breast_Cancer_CCI_Comprehensive_Analysis_Report.html`

## Citation Format

### In-text Citation
```
(Author et al., Year; PMID: 12345678)
```

Example:
> "consistent with previous reports demonstrating that the TREM2-APOE pathway drives microglial phenotype (Krasemann et al., 2017; PMID: 28930663)"

### References Section
```html
<a href="https://pubmed.ncbi.nlm.nih.gov/28930663/" class="reference" target="_blank">PMID: 28930663</a> - Brief description
```

## Cross-Reference Rules

1. **Every in-text PMID** → must appear in References section
2. **Every Reference** → must be cited at least once in body
3. **No orphan citations** (in body but not in References)

## Report Generation Workflow

```
Part 1 해석 작성 → /interpretations/part1.md 저장
        ↓
Part 2 해석 작성 → /interpretations/part2.md 저장
        ↓
Part 3 해석 작성 → /interpretations/part3.md 저장
        ↓
모든 Part 읽기 → generate_html_report()로 통합
```

**Important**: 각 Part 해석은 FilesystemBackend에 저장되고, 마지막에 한 번만 HTML 생성

## biomedical-literature-search Integration

### Citation Flow (Per Part)

```
search_literature_for_context()  # Part별 검색
        ↓
    papers: [{pmid, title, authors}]
        ↓
    Write Part interpretation with citations
        ↓
    Save to /interpretations/partN.md
        ↓
    (After all parts) generate_html_report(references=[all cited papers])
```

### Data Transformation

```python
# From search_literature_for_context
{"papers": [{"pmid": "28930663", "title": "The TREM2-APOE...", "authors": "Krasemann S"}]}

# To generate_html_report
{"references": [{"pmid": "28930663", "title": "The TREM2-APOE Pathway..."}]}
```

## Tool Usage

```python
generate_html_report(
    parts={
        "title": "...",
        "part1": {
            "Analysis Name": {
                "interpretation": "Finding... (Author et al., 2023; PMID: 12345678)",
                "references": [{"pmid": "12345678", "title": "..."}]
            }
        },
        "references": [{"pmid": "12345678", "title": "..."}]  # All cited papers
    },
    output_path="report.html"
)
```

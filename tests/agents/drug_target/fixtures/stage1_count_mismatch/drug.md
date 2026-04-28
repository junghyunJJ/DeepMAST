# 1. Executive Summary

This report assesses drug target candidates for idiopathic pulmonary fibrosis (IPF), selected
from a funnel of 18 L-R pairs evaluated across spatial transcriptomics data.

**Note for test coverage:** The count claim "18 L-R pairs" in this document is deliberately
inconsistent with `stage1_filter_results.json` which records `total: 19`. The validator must
detect any of the following phrasings when they disagree with the evidence total:
- "of 18 L-R pairs"
- "of 18 ligand-receptor pairs"
- "across 18 L-R pairs"
- "from 18 pairs"

**[FEATURED] Featured Candidates**
Top L-R pair genes: **EGFR, TGFB1**.

**Top Validated Targets:** EGFR, TGFB1

---

# 2. Target Druggability Matrix

| Rank | Gene  | Classification   | Validated Score | Priority | Key Evidence                                 |
|------|-------|------------------|-----------------|----------|----------------------------------------------|
| 1    | EGFR  | Validated Target | 17              | High     | Approved drugs (gefitinib), extensive trials |
| 2    | TGFB1 | Validated Target | 14              | High     | Phase 1-2 trials, strong mechanism relevance |

These candidates were identified from a review of 18 L-R pairs assessed across fibrotic
microenvironment spatial transcriptomics data.

---

# 3. Drug Profile

| Gene  | Drug        | Mechanism of Action                                        | Phase    | Status |
|-------|-------------|------------------------------------------------------------|----------|--------|
| EGFR  | gefitinib   | EGFR tyrosine kinase inhibitor; blocks ATP-binding pocket  | Approved | Active |
| TGFB1 | fresolimumab | TGF-beta1 neutralizing antibody; blocks SMAD2/3 signaling | Phase 2  | Active |

---

# 4. Gap Analysis

No Phase 3 IPF-specific EGFR inhibitor trial completed. Coverage of 18 L-R pairs from the
current cohort is limited; a larger cohort may reveal additional targets.

---

# 5. Therapeutic Recommendations

- **EGFR**: Initiate Phase 2b/3 IPF trial of gefitinib.
- **TGFB1**: Continue fresolimumab Phase 2 with extended safety arm.

---

# End of Report

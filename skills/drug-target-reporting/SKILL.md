---
name: drug-target-reporting
description: Generate a guarded, evidence-grounded direct drug target report from completed evidence.
---

# Drug Target Reporting

## Your Role: GUARDED REPORT AUTHOR

Write `target_assessment.json` and a complete `drug.md` directly from local
evidence. Use only values in the Reference Card or loaded evidence. When data
is absent, omit the claim or write `not available in source data`. Keep
`[source: ...]` annotations in `drug.md` as deterministic audit provenance.

## Evidence hierarchy and calibration

1. `build_evidence_summary` is the factual Reference Card for scores, classes,
   drug names, and pathways.
2. `load_evidence_files(scope="hypothesis")` supplies grounded Section 4
   evidence and must not be replaced by memory or general knowledge.
3. Preserve integer rubric values and classification labels exactly. Use hedged
   language for exploratory or novel evidence. Do not infer an indication,
   mechanism, approval year, or safety claim absent from the evidence.
4. Clinical Compounds use OpenTargets data from `ot_<gene>.json` and
   `resolved_drugs.json`; Stage 3 is preclinical support only. Never remove an
   OpenTargets clinical drug during repair unless its source is empty.

## Initial write

1. Read this skill and `references/scoring_guide.md` with `read_skill_file`.
2. Call `load_lr_candidates`.
3. Call `build_evidence_summary` exactly once with
   `include_legacy_hypothesis=False`. Treat its Markdown template as a factual
   skeleton, replace every marker, and write a complete direct Markdown report.
4. Call `load_evidence_files` with `scope="hypothesis"` for Section 4.
5. Call `save_target_assessment` exactly once with the complete payload. In other words, save_target_assessment exactly once.
6. Call `save_drug_md` exactly once with `strip_unexpanded_markers=False`,
   after saving the assessment, then stop.

## Repair mode

When the request begins `## REPAIR MODE`, use only the embedded current
Markdown. Fix only listed issues. Do not read skills or call initial-write
tools, and do not regenerate `target_assessment.json`. Call `save_drug_md`
exactly once with `strip_unexpanded_markers=False`, then stop.

`DrugReportGuardrailMiddleware` owns deterministic validation, up to three
repair passes, Part 4, HTML, audits, and publication. Do not call those
post-write operations yourself.

## Section 4 contract

Author recommendations from hypothesis-scope evidence in this parser-compatible
form; include every required label and use `4.1.2`, `4.2.1`, or `4.3.1` next:

```markdown
## 4. Mechanistic Hypothesis Recommendations

#### 4.1.1. <hypothesis title>
**Category:** <category>
**Core Claim:** <grounded, hedged claim>
- Genes: <comma-separated genes>
- Pathways: <comma-separated pathways or data not available>
- Cell Types: <comma-separated cell types or data not available>
- Drugs: <comma-separated drugs or data not available>
**Falsifiable Prediction:** <prediction>
**Validation Approach:** <test>
```

## Non-negotiable boundaries

- NEVER create or read evidence/hypothesis_report.json.
- NEVER create or write report_data.json.
- Do not use `read_file`, `write_file`, `grep`, `execute`, general-purpose
  subagents, external databases, or a second writer.
- Gap Analysis must not be empty: state data limitations, missing evidence, or
  open questions.

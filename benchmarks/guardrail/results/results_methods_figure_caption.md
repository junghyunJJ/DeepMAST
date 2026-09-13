# Report-level guardrails for biological interpretation

## Results

### Overall report outcomes

Across repeated executions on the breast cancer dataset, Qwen3.5-122B produced complete reports meeting the predefined validation criteria in 16 of 20 Guardrail ON runs (80%) and none of 20 Guardrail OFF runs (0%). Eighteen ON runs produced a complete final report: 16 passed the common post-hoc checks, whereas two were classified as containing citation overclaims. The remaining two ON runs were stopped by the report guardrail before final report production. All 20 OFF runs produced complete reports, and each contained at least one confirmed hard error under the predefined policy. All 40 primary outcomes were resolved (Table 1; Fig. X A).

**Table 1. Final report outcomes with and without report-level guardrails.**

| Outcome | Guardrail ON | Guardrail OFF |
|---|---:|---:|
| Complete report passing predefined checks | 16/20 (80%) | 0/20 (0%) |
| Complete report with errors detected post hoc | 2/20 (10%) | 20/20 (100%) |
| Final output blocked by the report guardrail | 2/20 (10%) | 0/20 (0%) |

Values are n/20 (%). The three categories are mutually exclusive and exhaustive. A report classified as containing errors was produced successfully, but one or more hard errors were identified during the common post-hoc assessment. A blocked run did not produce the final report. These outcomes summarize the combined pipeline performance and do not independently quantify the causal contribution of correction or blocking.

### Documented correction

Within-run comparisons of Guardrail ON artifacts provided direct examples of correction. In run 25–BA, the reported LAMA5–ITGB4 combined score was changed from 0.8060 to 0.7171, matching the source-table value rounded to four decimal places (Fig. X B). A separate edit in the same run replaced a sentence proposing targeted therapeutic strategies with a description of spatial heterogeneity in ligand–receptor interactions, consistent with the predefined separation between Part 3 spatial/statistical interpretation and Part 4 therapeutic synthesis.

Of 78 available before/after Markdown file pairs, 58 differed in content, while all 78 retained the same heading sequence. The ON execution records contained 61 standard repair passes and five terminal repair passes. These observations document editing operations and specific corrections; file-change and repair-pass counts are not counts of uniquely corrected errors and do not establish that every edit improved scientific accuracy.

### Documented output blocking

Two ON runs were stopped at the Part 3 guardrail with one reported residual hard error each: a pathway–factor direction mismatch in run 16–BA and an inline citation overclaim in run 17–BA. Neither run produced synthesis Markdown or the final HTML report (Fig. X C). No OFF run was blocked before final report production. However, two complete ON reports failed the common post-hoc assessment despite passing their runtime guardrail checks. Thus, the observed correction and blocking functions did not ensure that every produced ON report met the subsequent common validation criteria.

## Methods

### Study design and guardrail conditions

We compared 20 previously performed Guardrail ON executions with 20 newly performed Guardrail OFF executions using Qwen3.5-122B on the same breast cancer input dataset. SNI was enabled in both conditions. The fixed literature collection comprised 100 documents and 1,553 chunks. Recorded generation settings and source inputs were matched to the historical controls. Run identifiers 16–25 and their AB/BA labels were retained to link the experimental records; the ON and OFF reports were generated separately, and the OFF reports were not the pre-repair drafts of their ON counterparts. The analysis therefore represents repeated computational executions of one dataset rather than independent biological samples.

In the ON condition, report-level validation, targeted correction, revalidation, and error-dependent output blocking operated on Parts 1–3 and the synthesis. These report-level interventions were disabled in the OFF condition. Generation prompts and tools, inline evidence-checking capabilities, and file-saving/execution recovery were retained. SNI configuration was held constant, although actual retrieval use could vary with agent behavior and guardrail execution. Correction was examined using before/after artifacts and repair records from the same ON execution; blocking was established from residual-error records, termination logs, and the absence of final outputs.

### Common post-hoc assessment

The primary endpoint was production of a complete report with zero hard errors under the common validation policy. Completeness required nonempty Part 1, Part 2, Part 3, synthesis Markdown, and final HTML artifacts. The policy included deterministic checks for source-data consistency and reporting-scope requirements, together with LLM-assisted evidence and citation checks where required. A confirmed content hard error established primary-endpoint failure even if other checks were unfinished. If deterministic checks already established failure, further semantic checks could be omitted; reported error counts in those cases are lower bounds. Passing required completion of the necessary checks with no hard errors. Missing required reports also failed the primary endpoint. All 20 executions in each condition remained in the denominator.

Post-hoc checks operated on separate working copies, and checksums were used to verify that the original reports and their evaluation copies were unchanged. Evaluation execution failures were distinguished from report-content errors. The recovery evaluator maintained a persistent event loop for reused asynchronous model clients and used schema-validated JSON responses with explicit serialization instructions when the original tool-response encoding failed. The model, evidence, classification rules, token limit, and remaining request deadlines were retained. Successfully completed checks were reused from content-addressed common post-hoc checkpoints; generation-time guardrail verdicts were not substituted for post-hoc assessments. Reports were not regenerated or repaired during reassessment.

Final outcome classification used report artifacts and common post-hoc verdicts rather than the original runner status alone. In particular, 18 OFF runs had received a failure status from a missing-RAG-audit check after report generation had completed. These were recorded as audit gaps rather than output blocks. Historical runtime guardrail verdicts were kept distinct from the recovered common post-hoc verdicts.

### Interpretation scope

The analysis was descriptive and assessed compliance with predefined reporting and consistency requirements. No separate blinded assessment of overall scientific accuracy was performed. Reporting-scope violations were not presumed to be fabricated biological claims, and the findings were not interpreted as a general hallucination rate. ON executions preceded the OFF executions, leaving calendar-time differences as a limitation; historical model-weight digests and complete sampling-parameter provenance were unavailable. The findings apply to this model and analysis setting and do not establish an effect across open models or biological datasets generally.

## Figure caption

**Figure X. Outcomes and documented functions of report-level guardrails.** **(A)** Final outcomes of 20 Guardrail ON and 20 Guardrail OFF executions using Qwen3.5-122B with SNI enabled on the same breast cancer dataset. Categories are mutually exclusive: complete reports passing the predefined validation checks, complete reports with at least one detected hard error, and runs blocked by the report guardrail. Counts and percentages use all 20 executions per condition. The ON/OFF contrast summarizes the combined pipeline outcome and does not isolate the causal contribution of correction or blocking. **(B)** Illustrative numerical correction in ON run 25–BA: the reported LAMA5–ITGB4 combined score changed from 0.8060 to 0.7171, matching the source-data value rounded to four decimal places. This is a single documented repair, not an aggregate correction-rate estimate. **(C)** The two observed ON output blocks. Each run terminated with one reported residual hard error in Part 3; neither synthesis Markdown nor the final HTML report was produced. The analysis evaluates predefined reporting and consistency requirements rather than overall scientific accuracy. ON controls were generated earlier than OFF runs.

---

Associated figure: [PDF](../figures/guardrail_effects.pdf) · [SVG](../figures/guardrail_effects.svg) · [PNG](../figures/guardrail_effects.png).

Source records: [final comparison](comparison.json), [run manifest](../metadata/manifest.json), [two-effect analysis](analysis_two_effects/two_effects_summary.md), [repair and blocking examples](../metadata/repair_examples.md), [recovery methods](../metadata/recovery_method.md), and [verification](../metadata/verification.json).

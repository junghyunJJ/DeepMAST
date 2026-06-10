# IPF Hypothesis Generation: qwen3.5:35b vs qwen3.5:122b

Date: 2026-06-09

Scope: DeepMAST drug-target hypothesis generation for idiopathic pulmonary fibrosis using the `--skip-evidence-assessor` resume path. This note compares the hypothesis-generation behavior of `qwen3.5:35b` and `qwen3.5:122b` across three independent result directories each.

## Bottom Line

In this constrained evidence-grounded hypothesis-generation task, `qwen3.5:35b` was more operationally stable than `qwen3.5:122b`.

This should not be interpreted as evidence that `qwen3.5:35b` has better general scientific reasoning ability than `qwen3.5:122b`. The narrower conclusion is:

> `qwen3.5:35b` better matched the current DeepMAST hypothesis-generation contract: schema adherence, conservative evidence attribution, consistent FEATURED-gene coverage, and deterministic validation behavior.

The current task rewards literal contract following more than broad narrative synthesis. In that setting, a smaller model can appear better if it follows the checklist more predictably.

## Validation Summary

| Model | Runs | Hypothesis quality | Retry behavior | Final report | Selection stability |
| --- | ---: | --- | --- | --- | --- |
| `qwen3.5:35b` | 3 | 3/3 PASS | 0 retries in all runs | 3/3 finalized | Highest: same core 6 candidates across runs |
| `qwen3.5:122b` | 3 | 3/3 PASS | retries in 2/3 runs | 3/3 finalized | Lower: 5 vs 6 retained hypotheses; `ICAM1-EZR` absent in 2/3 runs |

## qwen3.5:35b Results

Directories:
- `res_ipf_drugtarget1_35b`
- `res_ipf_drugtarget2_35b`
- `res_ipf_drugtarget3_35b`

Observed behavior:
- `hypothesis_quality: PASS` in all three runs.
- `hypothesis_retry: skipped` in all three runs.
- `hypothesis_retry_attempts: 0` in all three runs.
- `report_finalized: YES` in all three runs.
- Runtime range: 506.4s to 682.3s.

Retained hypothesis set was highly consistent:
- `ICAM1-MUC1` epithelial/AT2-intrinsic follow-up axis.
- `ICAM1-EZR` epithelial/AT2-intrinsic follow-up axis, with ICAM1 as the supported anchor and EZR as coexpression-context partner.
- `CD47` actionability follow-up candidate.
- `FN1` gene-level or actionability follow-up candidate.
- `ITGB2` gene-level or actionability follow-up candidate.
- `CD4` gene-level or actionability follow-up candidate.

Interpretation:
- `qwen3.5:35b` behaved like a conservative contract-following generator.
- It consistently preserved the Stage 1 intrinsic pair `ICAM1-EZR`, which is important because this pair is biologically grounded by `stage1_ICAM1--EZR.json` but asymmetric in Stage 2/3 support.
- It was less likely to compress or reinterpret the required candidate set.

Residual concerns:
- Some runs still include context partners such as `SDC2`, `THBS1`, or `HLA-DQB1` in biological entities without citing their corresponding Stage 1 pair in that hypothesis. This is not necessarily fatal, but it should be polished before manuscript use.
- `CD47` still requires careful wording because `stage3_CD47.json` has no ChEMBL `matched_drugs`; OpenTargets known-drug evidence and Stage 3 ChEMBL matched-drug evidence should not be conflated.
- `res_ipf_drugtarget3_35b` uses "fibrosis resolution" more strongly than ideal; manuscript polish should soften this to "fibrosis-relevant readouts" or similar language.

## qwen3.5:122b Results

Directories:
- `res_ipf_drugtarget1_122b`
- `res_ipf_drugtarget2_122b`
- `res_ipf_drugtarget3_122b`

Observed behavior:
- `hypothesis_quality: PASS` in all three runs.
- `report_finalized: YES` in all three runs.
- Retry was required in two runs:
  - `res_ipf_drugtarget1_122b`: retry success after 3 attempts; runtime 2381.2s.
  - `res_ipf_drugtarget2_122b`: retry success after 1 attempt; runtime 1344.6s.
  - `res_ipf_drugtarget3_122b`: retry skipped; runtime 638.4s.

Retained hypothesis set was less stable:
- `res_ipf_drugtarget1_122b`: retained 5 hypotheses; included `ICAM1-MUC1`, `CD47`, `ICAM1-ITGB2`, `FN1`, and `CD4`; did not retain `ICAM1-EZR`.
- `res_ipf_drugtarget2_122b`: retained 5 hypotheses; included `ICAM1-MUC1`, `CD47`, `FN1`, `CD4`, and `ITGB2`; did not retain `ICAM1-EZR`.
- `res_ipf_drugtarget3_122b`: retained 6 hypotheses; included `ICAM1-MUC1`, `ICAM1-EZR`, `CD47`, `FN1`, `ITGB2`, and `CD4`.

Interpretation:
- `qwen3.5:122b` appears more willing to synthesize, compress, and choose among candidates.
- That behavior may be useful for a reviewer or discussion-generation role, but it is less desirable for this pipeline stage, where the goal is reproducible evidence-grounded coverage under a strict schema.
- The omission of `ICAM1-EZR` in two of three runs is not necessarily a biological mistake, but it is a pipeline-level instability because `ICAM1-EZR` is one of the two interest-cell-intrinsic Stage 1 pairs and should usually be represented if the output is expected to preserve primary epithelial/AT2 follow-up candidates.

Residual concerns:
- Retry dependence makes `qwen3.5:122b` less attractive as the default generator for high-throughput runs.
- The 122b outputs can sound more polished, but the extra synthesis increases the chance of candidate compression or evidence-attribution drift.
- In one prior inspection, `CD47` wording risked conflating OpenTargets known-drug support with Stage 3 ChEMBL matched-drug evidence. This is a wording and attribution issue, not a reason to reject the run wholesale.

## Why 35b Can Look Better Here

The current hypothesis-generation stage is not a free-form scientific reasoning benchmark. It is a constrained report-artifact generation task with hard validation gates.

Key contract requirements:
- Use only evidence files that were actually loaded or validated.
- Cite exact filenames in `Evidence References`.
- Preserve 4-6 retained recommendations.
- Cover FEATURED genes.
- Keep mandatory thematic categories represented.
- Respect Stage 1 pair usage guidance:
  - `stage1_ICAM1--MUC1.json` and `stage1_ICAM1--EZR.json` can support primary epithelial/AT2-intrinsic claims.
  - depleted or spatial-niche-only Stage 1 pairs cannot support same-cell epithelial/AT2-intrinsic claims.
- Treat unsupported partners as context partners or readouts, not independent druggable targets.
- Save a valid `hypothesis_report.json` artifact for downstream rendering.

Under these conditions, a model that follows templates literally can outperform a larger model that tries to optimize the narrative. This is likely why `qwen3.5:35b` looked more stable.

A useful framing is:

> `qwen3.5:35b` was better calibrated to the current generator contract; `qwen3.5:122b` may still be better suited for higher-level scientific review, critique, or manuscript discussion after the evidence-grounded artifact has been generated.

## Recommended Interpretation for Manuscript or Internal Notes

Use this wording:

> In a constrained evidence-grounded hypothesis-generation setting, `qwen3.5:35b` showed higher operational reproducibility than `qwen3.5:122b`, passing all validation gates without retry and producing a more consistent retained hypothesis set across independent runs. This should not be interpreted as superior general reasoning capacity. Rather, the current task appears to reward literal schema adherence, conservative evidence attribution, and deterministic coverage more than broad narrative synthesis.

Avoid this wording:

> `qwen3.5:35b` is better than `qwen3.5:122b`.

That statement is too broad and not supported by this experiment.

## Practical Recommendation

For the current DeepMAST hypothesis-generation pipeline:
- Use `qwen3.5:35b` as the default production generator.
- Use `qwen3.5:122b` as an optional reviewer, critic, or secondary scientific synthesis model.
- Do not claim general model superiority from these results.
- If `qwen3.5:122b` is used as generator, add stronger deterministic guards around candidate coverage, especially retention of `ICAM1-EZR` when Stage 1 intrinsic evidence is present.

## Evidence Anchors

Trace files inspected:
- `res_ipf_drugtarget1_35b/trace_20260609_133050.log`
- `res_ipf_drugtarget2_35b/trace_20260609_133050.log`
- `res_ipf_drugtarget3_35b/trace_20260609_133050.log`
- `res_ipf_drugtarget1_122b/trace_20260609_121030.log`
- `res_ipf_drugtarget2_122b/trace_20260609_121030.log`
- `res_ipf_drugtarget3_122b/trace_20260609_121030.log`

Primary generated artifacts inspected:
- `res_ipf_drugtarget1_35b/evidence/hypothesis_report.json`
- `res_ipf_drugtarget2_35b/evidence/hypothesis_report.json`
- `res_ipf_drugtarget3_35b/evidence/hypothesis_report.json`
- `res_ipf_drugtarget1_122b/evidence/hypothesis_report.json`
- `res_ipf_drugtarget2_122b/evidence/hypothesis_report.json`
- `res_ipf_drugtarget3_122b/evidence/hypothesis_report.json`


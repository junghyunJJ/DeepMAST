---
name: drug-target-reporting
description: Generate guarded, evidence-grounded hybrid report sections from completed evidence.
---

# Drug Target Reporting

## Your role: guarded report author

Author exactly one `hybrid_report_sections/v1` payload through
`save_report_sections`. Qwen owns only canonical Section 4 hypotheses and 2–4
Section 5 recommendations in `report_sections.json`. Never author Markdown,
target assessment, report data, render metadata, Part 4, or HTML.

Jinja owns every rendered layout and factual value, the deterministic Section
5.1 execution summary, source-tag placement, and renderer-owned output
artifacts. The guardrail validates the rendered Markdown, repairs sections
when needed, and publishes only after final validation.

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
   `include_legacy_hypothesis=False`.
4. Call `load_evidence_files` with `scope="hypothesis"` for grounded Section 4
   content.
5. Build one `hybrid_report_sections/v1` payload:
   - `hypothesis_report` has 4–6 canonical hypotheses across Mechanism of
     Action, Therapeutic Strategy, Cross-Target Interaction, and Novel Pathway.
     Every hypothesis includes rank, title, category, core claim, biological
     entities, falsifiable prediction, validation approach, scores, and
     grounded evidence references.
   - `pipeline_recommendations` has 2–4 single-sentence, future-directed
     recommendations. Each has 1–3 deterministic supporting evidence paths and
     introduces no new quantitative claim.
6. Self-check the payload against loaded evidence, call `save_report_sections`
   exactly once, then stop.

## Repair mode

When the request begins `## REPAIR MODE`, use only the supplied current
sections payload and bounded validation findings. Repair only those findings,
call `save_report_sections` exactly once with the complete corrected payload,
then stop. Do not edit `drug.md`.

The guardrail re-renders and revalidates after every save. After at most three
failed repairs it does not publish Part 4 or HTML.

## Non-negotiable boundaries

- NEVER create or read `evidence/hypothesis_report.json`.
- NEVER create or write `report_data.json`, `target_assessment.json`, or
  `drug.md`.
- Do not use `read_file`, `write_file`, `grep`, `execute`, general-purpose
  subagents, external databases, or a second writer.
- Gap Analysis must not be empty: state data limitations, missing evidence, or
  open questions.

## Supported local Ollama diagnostic invocation

This invocation is diagnostic; no successful report was produced.

Use OpenAI-compatible Ollama because the writer needs tool schemas:

```bash
export OLLAMA_BASE_URL=http://localhost:6000
export OLLAMA_MODEL=qwen3.5:122b
python scripts/run_report_writer_only.py \
  --data-dir /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/final_bc_hybrid_qwen_test \
  --disease "breast cancer" \
  --provider ollama-openai \
  --model qwen3.5:122b
```
